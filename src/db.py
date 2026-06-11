from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

import psycopg
from psycopg.rows import dict_row


@dataclass
class BuyPosition:
    id: int
    quantity_btc: float
    unit_price_usd: float
    fee_usd: float


@dataclass
class PriceSample:
    sampled_at: datetime
    price_usd: float
    source: str


@dataclass
class HourlyMetric:
    hour_start: datetime
    sample_count: int
    min_price_usd: float
    max_price_usd: float
    avg_price_usd: float
    last_price_usd: float


def get_connection(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn)


def insert_buy(
    conn: psycopg.Connection,
    platform_name: str,
    asset_symbol: str,
    quantity_btc: float,
    unit_price_usd: float,
    fee_usd: float,
    strategy_tag: str,
    transaction_at: datetime | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO transactions (
                platform_name,
                asset_symbol,
                action,
                quantity_btc,
                unit_price_usd,
                fee_usd,
                status,
                strategy_tag,
                transaction_at
            )
            VALUES (%s, %s, 'BUY', %s, %s, %s, 'OPEN', %s, COALESCE(%s, NOW()))
            RETURNING id
            """,
            (platform_name, asset_symbol, quantity_btc, unit_price_usd, fee_usd, strategy_tag, transaction_at),
        )
        buy_id = cur.fetchone()[0]
    conn.commit()
    return buy_id


def get_open_buys(conn: psycopg.Connection, asset_symbol: str) -> List[BuyPosition]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, quantity_btc, unit_price_usd, fee_usd
            FROM transactions
            WHERE asset_symbol = %s
              AND action = 'BUY'
              AND status = 'OPEN'
                        ORDER BY transaction_at ASC
            """,
            (asset_symbol,),
        )
        rows = cur.fetchall()

    return [
        BuyPosition(
            id=row["id"],
            quantity_btc=float(row["quantity_btc"]),
            unit_price_usd=float(row["unit_price_usd"]),
            fee_usd=float(row["fee_usd"]),
        )
        for row in rows
    ]


def close_with_sell(
    conn: psycopg.Connection,
    buy_position: BuyPosition,
    platform_name: str,
    asset_symbol: str,
    sell_unit_price_usd: float,
    sell_fee_usd: float,
    strategy_tag: str,
    transaction_at: datetime | None = None,
) -> int:
    gross_buy = buy_position.quantity_btc * buy_position.unit_price_usd
    gross_sell = buy_position.quantity_btc * sell_unit_price_usd
    realized_pnl = gross_sell - gross_buy - buy_position.fee_usd - sell_fee_usd

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO transactions (
                platform_name,
                asset_symbol,
                action,
                quantity_btc,
                unit_price_usd,
                fee_usd,
                paired_buy_transaction_id,
                realized_pnl_usd,
                status,
                strategy_tag,
                transaction_at
            )
            VALUES (%s, %s, 'SELL', %s, %s, %s, %s, %s, 'CLOSED', %s, COALESCE(%s, NOW()))
            RETURNING id
            """,
            (
                platform_name,
                asset_symbol,
                buy_position.quantity_btc,
                sell_unit_price_usd,
                sell_fee_usd,
                buy_position.id,
                realized_pnl,
                strategy_tag,
                transaction_at,
            ),
        )
        sell_id = cur.fetchone()[0]

        cur.execute(
            """
            UPDATE transactions
            SET status = 'CLOSED'
            WHERE id = %s
            """,
            (buy_position.id,),
        )

    conn.commit()
    return sell_id


def create_transaction(
    conn: psycopg.Connection,
    *,
    platform_name: str,
    asset_symbol: str,
    action: str,
    quantity_btc: float,
    unit_price_usd: float,
    fee_usd: float,
    status: str,
    transaction_at: datetime,
    strategy_tag: str | None,
    notes: str | None,
    paired_buy_transaction_id: int | None = None,
    realized_pnl_usd: float | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO transactions (
                platform_name,
                asset_symbol,
                action,
                quantity_btc,
                unit_price_usd,
                fee_usd,
                paired_buy_transaction_id,
                realized_pnl_usd,
                status,
                transaction_at,
                strategy_tag,
                notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                platform_name,
                asset_symbol,
                action,
                quantity_btc,
                unit_price_usd,
                fee_usd,
                paired_buy_transaction_id,
                realized_pnl_usd,
                status,
                transaction_at,
                strategy_tag,
                notes,
            ),
        )
        transaction_id = cur.fetchone()[0]
    conn.commit()
    return transaction_id


def list_transactions(
    conn: psycopg.Connection,
    *,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT
                id,
                platform_name,
                asset_symbol,
                action,
                quantity_btc,
                unit_price_usd,
                fee_usd,
                paired_buy_transaction_id,
                realized_pnl_usd,
                status,
                transaction_at,
                strategy_tag,
                notes,
                executed_at,
                created_at
            FROM transactions
            ORDER BY transaction_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    return [dict(row) for row in rows]


def insert_price_sample(
    conn: psycopg.Connection,
    *,
    asset_symbol: str,
    source: str,
    price_usd: float,
    sampled_at: datetime,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO price_samples (asset_symbol, source, price_usd, sampled_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (asset_symbol, source, sampled_at)
            DO UPDATE SET price_usd = EXCLUDED.price_usd
            RETURNING id
            """,
            (asset_symbol, source, price_usd, sampled_at),
        )
        row_id = cur.fetchone()[0]
    conn.commit()
    return row_id


def list_price_samples(
    conn: psycopg.Connection,
    *,
    asset_symbol: str,
    hours: int,
) -> List[PriceSample]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT sampled_at, price_usd, source
            FROM price_samples
            WHERE asset_symbol = %s
              AND sampled_at >= NOW() - make_interval(hours => %s)
            ORDER BY sampled_at ASC
            """,
            (asset_symbol, hours),
        )
        rows = cur.fetchall()

    return [
        PriceSample(
            sampled_at=row["sampled_at"],
            price_usd=float(row["price_usd"]),
            source=row["source"],
        )
        for row in rows
    ]


def get_hourly_metrics(
    conn: psycopg.Connection,
    *,
    asset_symbol: str,
    hours: int,
) -> List[HourlyMetric]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            WITH base AS (
                SELECT
                    date_trunc('hour', sampled_at) AS hour_start,
                    sampled_at,
                    price_usd
                FROM price_samples
                WHERE asset_symbol = %s
                  AND sampled_at >= NOW() - make_interval(hours => %s)
            ),
            agg AS (
                SELECT
                    hour_start,
                    COUNT(*) AS sample_count,
                    MIN(price_usd) AS min_price_usd,
                    MAX(price_usd) AS max_price_usd,
                    AVG(price_usd) AS avg_price_usd
                FROM base
                GROUP BY hour_start
            ),
            latest AS (
                SELECT DISTINCT ON (hour_start)
                    hour_start,
                    price_usd AS last_price_usd
                FROM base
                ORDER BY hour_start, sampled_at DESC
            )
            SELECT
                agg.hour_start,
                agg.sample_count,
                agg.min_price_usd,
                agg.max_price_usd,
                agg.avg_price_usd,
                latest.last_price_usd
            FROM agg
            INNER JOIN latest USING (hour_start)
            ORDER BY agg.hour_start ASC
            """,
            (asset_symbol, hours),
        )
        rows = cur.fetchall()

    return [
        HourlyMetric(
            hour_start=row["hour_start"],
            sample_count=row["sample_count"],
            min_price_usd=float(row["min_price_usd"]),
            max_price_usd=float(row["max_price_usd"]),
            avg_price_usd=float(row["avg_price_usd"]),
            last_price_usd=float(row["last_price_usd"]),
        )
        for row in rows
    ]
