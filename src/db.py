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


@dataclass
class WalletSummary:
    """Aggregated wallet state for an asset."""
    net_deposits: float
    realized_pnl: float
    open_cost_basis: float


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
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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


def get_latest_price_sample_time(
    conn: psycopg.Connection,
    *,
    asset_symbol: str,
    source: str,
) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT MAX(sampled_at)
            FROM price_samples
            WHERE asset_symbol = %s
              AND source = %s
            """,
            (asset_symbol, source),
        )
        row = cur.fetchone()

    if not row or row[0] is None:
        return None
    return row[0]


def get_price_sample_time_bounds(
    conn: psycopg.Connection,
    *,
    asset_symbol: str,
    source: str,
) -> tuple[datetime | None, datetime | None]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT MIN(sampled_at), MAX(sampled_at)
            FROM price_samples
            WHERE asset_symbol = %s
              AND source = %s
            """,
            (asset_symbol, source),
        )
        row = cur.fetchone()

    if not row:
        return (None, None)
    return (row[0], row[1])


def upsert_price_samples(
    conn: psycopg.Connection,
    *,
    asset_symbol: str,
    source: str,
    samples: list[tuple[datetime, float]],
) -> int:
    if not samples:
        return 0

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO price_samples (asset_symbol, source, price_usd, sampled_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (asset_symbol, source, sampled_at)
            DO UPDATE SET price_usd = EXCLUDED.price_usd
            """,
            [(asset_symbol, source, price_usd, sampled_at) for sampled_at, price_usd in samples],
        )

    conn.commit()
    return len(samples)


def ensure_sync_state_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_state (
                state_key TEXT PRIMARY KEY,
                state_value TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    conn.commit()


def get_sync_state(conn: psycopg.Connection, *, state_key: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT state_value
            FROM sync_state
            WHERE state_key = %s
            """,
            (state_key,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return row[0]


def set_sync_state(conn: psycopg.Connection, *, state_key: str, state_value: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sync_state (state_key, state_value)
            VALUES (%s, %s)
            ON CONFLICT (state_key)
            DO UPDATE SET state_value = EXCLUDED.state_value, updated_at = NOW()
            """,
            (state_key, state_value),
        )
    conn.commit()


def delete_sync_state(conn: psycopg.Connection, *, state_key: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM sync_state
            WHERE state_key = %s
            """,
            (state_key,),
        )
    conn.commit()


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


def get_last_buy_time(
    conn: psycopg.Connection,
    asset_symbol: str,
) -> datetime | None:
    """
    Return the transaction_at of the most recent BUY for the asset.
    
    Returns None if no BUY transactions exist.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT transaction_at
            FROM transactions
            WHERE asset_symbol = %s
              AND action = 'BUY'
            ORDER BY transaction_at DESC
            LIMIT 1
            """,
            (asset_symbol,),
        )
        row = cur.fetchone()
    
    return row[0] if row else None


def get_wallet_summary(
    conn: psycopg.Connection,
    asset_symbol: str,
) -> WalletSummary:
    """
    Compute aggregated wallet state for an asset.
    
    Returns:
        WalletSummary with net_deposits, realized_pnl, and open_cost_basis
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            WITH deposits_withdrawals AS (
                SELECT
                    COALESCE(SUM(CASE WHEN action = 'DEPOSIT' THEN quantity_btc * unit_price_usd - fee_usd ELSE 0 END), 0) -
                    COALESCE(SUM(CASE WHEN action = 'WITHDRAWAL' THEN quantity_btc * unit_price_usd + fee_usd ELSE 0 END), 0) AS net_deposits,
                    COALESCE(SUM(CASE WHEN action = 'SELL' THEN realized_pnl_usd ELSE 0 END), 0) AS realized_pnl
                FROM transactions
                WHERE asset_symbol = %s
            ),
            open_buys AS (
                SELECT
                    COALESCE(SUM((quantity_btc * unit_price_usd) + fee_usd), 0) AS open_cost_basis
                FROM transactions
                WHERE asset_symbol = %s
                  AND action = 'BUY'
                  AND status = 'OPEN'
            )
            SELECT
                dw.net_deposits,
                dw.realized_pnl,
                ob.open_cost_basis
            FROM deposits_withdrawals dw
            CROSS JOIN open_buys ob
            """,
            (asset_symbol, asset_symbol),
        )
        row = cur.fetchone()
    
    if not row:
        return WalletSummary(net_deposits=0.0, realized_pnl=0.0, open_cost_basis=0.0)
    
    return WalletSummary(
        net_deposits=float(row["net_deposits"]),
        realized_pnl=float(row["realized_pnl"]),
        open_cost_basis=float(row["open_cost_basis"]),
    )


def get_price_samples_window(
    conn: psycopg.Connection,
    asset_symbol: str,
    from_minutes_ago: int | None = None,
    lookback_days: int = 90,
) -> list[PriceSample]:
    """
    Get all price samples within the lookback window.
    
    Args:
        conn: Database connection
        asset_symbol: Asset to fetch samples for
        from_minutes_ago: Fetch samples from this many minutes ago to now (if None, fetch all recent)
        lookback_days: How many days back to search
    
    Returns:
        List of PriceSample rows sorted by sampled_at ASC
    """
    with conn.cursor(row_factory=dict_row) as cur:
        if from_minutes_ago:
            # Fetch samples within a specific window
            cur.execute(
                """
                SELECT asset_symbol, source, price_usd, sampled_at
                FROM price_samples
                WHERE asset_symbol = %s
                  AND sampled_at >= NOW() - INTERVAL '%s minutes'
                ORDER BY sampled_at ASC
                """,
                (asset_symbol, from_minutes_ago),
            )
        else:
            # Fetch all samples from lookback_days
            cur.execute(
                """
                SELECT asset_symbol, source, price_usd, sampled_at
                FROM price_samples
                WHERE asset_symbol = %s
                  AND sampled_at >= NOW() - INTERVAL '%s days'
                ORDER BY sampled_at ASC
                """,
                (asset_symbol, lookback_days),
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
