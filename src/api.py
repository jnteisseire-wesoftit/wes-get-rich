import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import Settings
from .db import (
    create_transaction,
    delete_sync_state,
    ensure_sync_state_table,
    get_connection,
    get_sync_state,
    get_hourly_metrics,
    get_price_sample_time_bounds,
    insert_price_sample,
    list_price_samples,
    list_transactions,
    set_sync_state,
    upsert_price_samples,
)
from .services.binance.service import BinanceCredentials, BinanceService, BinanceServiceError
from .services.kraken.service import KrakenService, KrakenServiceError
from .services.kraken.backfill import backfill_kraken_ohlc
from .services.backtest.service import run_simulation
from .main import run_cycle
from .strategy import FeeAdjustedPnL, calculate_fee_adjusted_pnl


class TransactionCreateRequest(BaseModel):
    platform_name: str = Field(min_length=2, max_length=50)
    asset_symbol: str = Field(min_length=2, max_length=20)
    action: Literal["BUY", "SELL", "DEPOSIT", "WITHDRAWAL"]
    quantity_btc: float | None = Field(default=None, gt=0)
    unit_price_chf: float | None = Field(default=None, gt=0)
    fee_chf: float | None = Field(default=None, ge=0)
    realized_pnl_chf: float | None = None
    unit_price_usd: float | None = Field(default=None, gt=0)
    fee_usd: float | None = Field(default=None, ge=0)
    status: Literal["OPEN", "CLOSED"] = "OPEN"
    transaction_at: datetime
    strategy_tag: str | None = None
    notes: str | None = None
    paired_buy_transaction_id: int | None = None
    realized_pnl_usd: float | None = None


class TransactionCreateResponse(BaseModel):
    id: int


class TransactionItem(BaseModel):
    id: int
    platform_name: str
    asset_symbol: str
    action: str
    quantity_btc: float
    unit_price_chf: float
    fee_chf: float
    realized_pnl_chf: float | None
    unit_price_usd: float
    fee_usd: float
    paired_buy_transaction_id: int | None
    realized_pnl_usd: float | None
    status: str
    transaction_at: datetime
    strategy_tag: str | None
    notes: str | None
    current_price_chf: float | None
    unrealized_pnl_chf: float | None
    profitability_status: Literal["PROFIT", "LOSS", "BREAKEVEN", "UNKNOWN"]
    profitability_color: Literal["green", "red", "gray"]
    executed_at: datetime
    created_at: datetime


class MarketPriceResponse(BaseModel):
    asset_symbol: str
    price_chf: float


class BotStatusResponse(BaseModel):
    running: bool


class BinancePriceResponse(BaseModel):
    symbol: str
    price: float


class KrakenBalanceResponse(BaseModel):
    live_trading_enabled: bool
    balances: dict[str, float]


class BinanceOrderRequest(BaseModel):
    symbol: str = Field(default="BTCUSDT", min_length=6, max_length=20)
    side: Literal["BUY", "SELL"]
    quantity: float | None = Field(default=None, gt=0)
    quote_order_qty: float | None = Field(default=None, gt=0)
    test_order: bool = True
    persist_transaction: bool = False
    platform_name: str = "binance"
    transaction_at: datetime | None = None
    strategy_tag: str | None = "binance-api"
    notes: str | None = None


class BinanceOrderResponse(BaseModel):
    symbol: str
    side: str
    test_order: bool
    order_id: int | None = None
    status: str | None = None
    executed_qty: float | None = None
    cummulative_quote_qty: float | None = None
    average_price: float | None = None
    recorded_transaction_id: int | None = None


class KrakenOrderRequest(BaseModel):
    side: Literal["BUY", "SELL"]
    quantity_btc: float | None = Field(default=None, gt=0)
    quote_order_qty: float | None = Field(default=None, gt=0)
    validate_only: bool = True
    persist_transaction: bool = False
    platform_name: str = "kraken"
    transaction_at: datetime | None = None
    strategy_tag: str | None = "kraken-api"
    notes: str | None = None


class KrakenOrderResponse(BaseModel):
    pair: str
    side: str
    validate_only: bool
    order_description: str | None = None
    txid: list[str] = Field(default_factory=list)
    estimated_price_chf: float | None = None
    estimated_quantity_btc: float | None = None
    recorded_transaction_id: int | None = None


class PriceSampleItem(BaseModel):
    sampled_at: datetime
    price_chf: float
    source: str


class StrategyHistoryResponse(BaseModel):
    asset_symbol: str
    source: str
    interval_minutes: int
    samples: list[PriceSampleItem]


class HourlyMetricItem(BaseModel):
    hour_start: datetime
    sample_count: int
    min_price_chf: float
    max_price_chf: float
    avg_price_chf: float
    last_price_chf: float


class StrategyMetricsResponse(BaseModel):
    asset_symbol: str
    source: str
    generated_at: datetime
    window_hours: int
    current_price_chf: float | None
    min_price_chf: float | None
    max_price_chf: float | None
    avg_price_chf: float | None
    change_window_pct: float | None
    hourly: list[HourlyMetricItem]


class CollectSampleResponse(BaseModel):
    id: int
    asset_symbol: str
    source: str
    sampled_at: datetime
    price_chf: float


class FeeAdjustedPnLResponse(BaseModel):
    gross_pnl_chf: float
    expected_sell_fee_chf: float
    net_pnl_chf: float
    fee_adjusted_pnl_pct: float
    break_even_price_chf: float


class OpenPositionMetrics(BaseModel):
    transaction_id: int
    quantity_btc: float
    cost_basis_chf: float
    current_value_chf: float
    gross_pnl_chf: float
    fee_adjusted_pnl: FeeAdjustedPnLResponse


class PortfolioMetricsResponse(BaseModel):
    asset_symbol: str
    current_price_chf: float
    generated_at: datetime
    exchange_fee_rate: float
    total_invested_chf: float
    total_realized_profit_chf: float
    total_realized_loss_chf: float
    gross_unrealized_pnl_chf: float
    fee_adjusted_unrealized_pnl_chf: float
    total_fees_paid_chf: float
    expected_exit_fees_chf: float
    open_positions: list[OpenPositionMetrics]
    cash_balance_chf: float
    live_btc_balance: float
    live_btc_value_chf: float
    total_portfolio_value_chf: float


class SimulationParametersRequest(BaseModel):
    wallet_fraction_per_trade: float = Field(default=0.10, gt=0, le=1.0)
    max_open_positions: int = Field(default=10, ge=1)
    min_minutes_between_trades: int = Field(default=1440, ge=1)
    take_profit_pct: float = Field(default=5.0, gt=0)
    stop_loss_pct: float = Field(default=-2.0, lt=0)
    dynamic_stop_loss_atr_multiplier: float = Field(default=1.5, gt=0)
    trend_short_window_hours: int = Field(default=6, ge=1)
    trend_long_window_hours: int = Field(default=24, ge=1)
    bearish_exit_min_cycles: int = Field(default=2, ge=1)
    enable_bearish_exit: bool = False
    exchange_fee_rate: float = Field(default=0.004, ge=0, le=0.1)


class SimulationCreateRequest(BaseModel):
    simulation_name: str = Field(min_length=3, max_length=100)
    asset_symbol: str = Field(default="BTC", min_length=2, max_length=20)
    start_at: datetime
    end_at: datetime
    initial_wallet: float = Field(gt=0)
    parameters: SimulationParametersRequest


class SimulationMetricsResponse(BaseModel):
    total_buys: int
    total_sells: int
    realized_pnl: float
    unrealized_pnl_at_end: float
    total_return_pct: float
    win_rate_pct: float
    crash_guard_activations: int


class SimulationTransactionResponse(BaseModel):
    id: int
    action: str
    quantity: float
    unit_price: float
    fee: float
    trigger_rule: str
    realized_pnl: float | None
    simulated_at: datetime


class SimulationResultsResponse(BaseModel):
    simulation_id: int
    name: str
    asset_symbol: str
    start_at: datetime
    end_at: datetime
    initial_wallet: float
    parameters: dict
    metrics: SimulationMetricsResponse
    transactions: list[SimulationTransactionResponse]
    computed_at: datetime


class SimulationItem(BaseModel):
    simulation_id: int
    name: str
    asset_symbol: str
    start_at: datetime
    end_at: datetime
    initial_wallet: float
    total_return_pct: float
    win_rate_pct: float
    crash_guard_activations: int
    created_at: datetime


def _to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _pick_quote_value(chf_value: float | None, usd_value: float | None, *, default: float | None = 0.0) -> float | None:
    if chf_value is not None:
        return chf_value
    if usd_value is not None:
        return usd_value
    return default


def _profitability_for_transaction(
    *,
    action: str,
    status: str,
    quantity_btc: float,
    unit_price_chf: float,
    fee_chf: float,
    realized_pnl_chf: float | None,
    current_price_chf: float | None,
) -> tuple[float | None, Literal["PROFIT", "LOSS", "BREAKEVEN", "UNKNOWN"], Literal["green", "red", "gray"]]:
    pnl_now_chf: float | None = None

    if status == "CLOSED":
        pnl_now_chf = realized_pnl_chf
    elif action == "BUY" and current_price_chf is not None:
        current_value = quantity_btc * current_price_chf
        cost_basis = (quantity_btc * unit_price_chf) + fee_chf
        pnl_now_chf = current_value - cost_basis
    elif action == "SELL" and realized_pnl_chf is not None:
        pnl_now_chf = realized_pnl_chf

    if pnl_now_chf is None:
        return None, "UNKNOWN", "gray"
    if pnl_now_chf > 0:
        return pnl_now_chf, "PROFIT", "green"
    if pnl_now_chf < 0:
        return pnl_now_chf, "LOSS", "red"
    return pnl_now_chf, "BREAKEVEN", "gray"


def _compute_cash_balance(rows: list[dict]) -> float:
    cash_balance = 0.0
    for row in rows:
        quantity = float(row["quantity_btc"] or 0)
        unit_price = float(row["unit_price_usd"] or 0)
        fee = float(row["fee_usd"] or 0)
        notional = quantity * unit_price

        if row["action"] == "DEPOSIT":
            cash_balance += notional - fee
        elif row["action"] == "WITHDRAWAL":
            cash_balance -= notional + fee
        elif row["action"] == "BUY":
            cash_balance -= notional + fee
        elif row["action"] == "SELL":
            cash_balance += notional - fee

    return cash_balance


def _extract_live_cash_balance(balances: dict[str, float]) -> float | None:
    for symbol in ("CHF", "ZCHF"):
        if symbol in balances:
            return float(balances[symbol])
    return None


def _extract_live_btc_balance(balances: dict[str, float]) -> float:
    return float(balances.get("XXBT", balances.get("XBT", 0.0)))


def _get_effective_exchange_fee_rate(settings: Settings) -> float:
    try:
        if settings.kraken_api_key and settings.kraken_api_secret:
            return _build_kraken_service(settings).fetch_fee_rate(_kraken_pair(settings))
    except (KrakenServiceError, AttributeError) as exc:
        print(f"fee tier warning, using configured fallback: {exc}")
    return settings.exchange_fee_rate


def _compute_open_invested(rows: list[dict]) -> float:
    return sum(
        (float(row["quantity_btc"] or 0) * float(row["unit_price_usd"] or 0))
        + float(row["fee_usd"] or 0)
        for row in rows
        if row["action"] == "BUY" and row["status"] == "OPEN"
    )


def _build_binance_service(settings: Settings) -> BinanceService:
    creds = None
    if settings.binance_api_key and settings.binance_api_secret:
        creds = BinanceCredentials(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
        )

    return BinanceService(base_url=settings.binance_base_url, credentials=creds)


def _build_kraken_service(settings: Settings) -> KrakenService:
    return KrakenService(
        base_url=settings.kraken_base_url,
        api_key=settings.kraken_api_key,
        api_secret=settings.kraken_api_secret,
    )


def _kraken_pair(settings: Settings) -> str:
    return settings.kraken_trading_pair.upper()


def _normalize_asset(asset_symbol: str) -> str:
    normalized = asset_symbol.upper()
    if normalized != "BTC":
        raise HTTPException(status_code=400, detail="Only BTC is supported for now")
    return normalized


def _collect_and_store_sample(settings: Settings) -> CollectSampleResponse:
    sampled_at = datetime.now(timezone.utc)

    source = "kraken"
    try:
        price_chf = _build_kraken_service(settings).fetch_spot_price_usd(pair=_kraken_pair(settings))
    except KrakenServiceError as e:
        # Kraken failed - try CoinGecko as fallback
        try:
            from .services.coingecko.service import fetch_current_price
            source = "coingecko"
            price_chf = fetch_current_price(asset_symbol="BTC", vs_currency="usd")
        except Exception as cg_error:
            raise HTTPException(
                status_code=503,
                detail=f"All price sources unavailable. Kraken: {str(e)}, CoinGecko: {str(cg_error)}"
            ) from e

    conn = get_connection(settings.dsn)
    try:
        sample_id = insert_price_sample(
            conn,
            asset_symbol="BTC",
            source=source,
            price_usd=price_chf,
            sampled_at=sampled_at,
        )
    finally:
        conn.close()

    return CollectSampleResponse(
        id=sample_id,
        asset_symbol="BTC",
        source=source,
        sampled_at=sampled_at,
        price_chf=price_chf,
    )


def _sync_kraken_history_to_db(settings: Settings) -> int:
    now = datetime.now(timezone.utc)
    lookback_days = max(1, settings.kraken_history_lookback_days)
    interval_minutes = max(1, settings.kraken_history_interval_minutes)
    cutoff = now - timedelta(days=lookback_days)
    kraken = _build_kraken_service(settings)
    backfill_cursor_key = f"kraken_trades_backfill_cursor_ns_BTC_{interval_minutes}m"

    def _to_bucket_start(ts: datetime) -> datetime:
        minute_bucket = (ts.minute // interval_minutes) * interval_minutes
        return ts.replace(minute=minute_bucket, second=0, microsecond=0)

    conn = get_connection(settings.dsn)
    try:
        ensure_sync_state_table(conn)
        oldest, latest = get_price_sample_time_bounds(conn, asset_symbol="BTC", source="kraken")

        if latest is None:
            since_dt = cutoff
        else:
            since_dt = latest

        since_epoch = int(since_dt.timestamp()) + 1
        now_epoch = int(now.timestamp())
        total_upserted = 0

        # Keep near-real-time candles fresh with OHLC pagination.
        for _ in range(1000):
            batch = kraken.fetch_ohlc_close_prices_batch(
                pair="XBTUSD",
                interval_minutes=interval_minutes,
                since_epoch=since_epoch,
            )
            if not batch.samples:
                break

            records = [
                (sample.sampled_at, sample.price_usd)
                for sample in batch.samples
                if cutoff <= sample.sampled_at <= now
            ]
            total_upserted += upsert_price_samples(
                conn,
                asset_symbol="BTC",
                source="kraken",
                samples=records,
            )

            if batch.last <= since_epoch:
                break

            since_epoch = batch.last
            if since_epoch >= now_epoch:
                break

        # Backfill deeper history (older than OHLC retention) using trades pagination.
        oldest, _ = get_price_sample_time_bounds(conn, asset_symbol="BTC", source="kraken")
        if oldest is None or oldest > cutoff:
            saved_cursor = get_sync_state(conn, state_key=backfill_cursor_key)
            backfill_cursor = int(saved_cursor) if saved_cursor else int(cutoff.timestamp() * 1_000_000_000)
            now_ns = int(now.timestamp() * 1_000_000_000)

            for _ in range(50):
                batch = kraken.fetch_trades_batch(pair="XBTUSD", since_cursor=backfill_cursor)
                if not batch.trades or batch.last <= backfill_cursor:
                    break

                close_by_bucket: dict[datetime, float] = {}
                for trade in batch.trades:
                    if trade.traded_at < cutoff or trade.traded_at > now:
                        continue
                    close_by_bucket[_to_bucket_start(trade.traded_at)] = trade.price_usd

                records = sorted(close_by_bucket.items(), key=lambda item: item[0])
                total_upserted += upsert_price_samples(
                    conn,
                    asset_symbol="BTC",
                    source="kraken",
                    samples=records,
                )

                backfill_cursor = batch.last
                set_sync_state(conn, state_key=backfill_cursor_key, state_value=str(backfill_cursor))

                if backfill_cursor >= now_ns:
                    break

            oldest_after, _ = get_price_sample_time_bounds(conn, asset_symbol="BTC", source="kraken")
            if oldest_after is not None and oldest_after <= cutoff:
                delete_sync_state(conn, state_key=backfill_cursor_key)

        if total_upserted > 0:
            print(f"kraken sync inserted/updated {total_upserted} candles")

        return total_upserted
    finally:
        conn.close()


def _fetch_kraken_history_for_hours(settings: Settings, hours: int) -> list[PriceSampleItem]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    interval_minutes = max(1, settings.kraken_history_interval_minutes)
    kraken = _build_kraken_service(settings)
    since_epoch = int(cutoff.timestamp())
    now_epoch = int(now.timestamp())
    items: list[PriceSampleItem] = []

    for _ in range(200):
        batch = kraken.fetch_ohlc_close_prices_batch(
            pair="XBTUSD",
            interval_minutes=interval_minutes,
            since_epoch=since_epoch,
        )

        if not batch.samples:
            break

        items.extend(
            [
                PriceSampleItem(sampled_at=s.sampled_at, price_chf=s.price_usd, source="kraken")
                for s in batch.samples
                if cutoff <= s.sampled_at <= now
            ]
        )

        if batch.last <= since_epoch:
            break

        since_epoch = batch.last
        if since_epoch >= now_epoch:
            break

    items.sort(key=lambda sample: sample.sampled_at)
    deduped: dict[datetime, PriceSampleItem] = {}
    for item in items:
        deduped[item.sampled_at] = item
    return [deduped[dt] for dt in sorted(deduped.keys())]


async def _price_sampler_loop() -> None:
    settings = Settings()
    sleep_seconds = max(300, settings.price_sample_interval_seconds)

    while True:
        try:
            _sync_kraken_history_to_db(settings)
        except Exception as exc:  # pragma: no cover - long-running task resilience
            print(f"price sampler warning: {exc}")

        await asyncio.sleep(sleep_seconds)


async def _sync_kraken_trades_on_startup() -> None:
    try:
        _sync_kraken_trades_to_db(Settings())
    except Exception as exc:  # pragma: no cover - startup resilience
        print(f"kraken trade sync warning: {exc}")


async def _bot_loop() -> None:
    settings = Settings()
    interval_seconds = max(5, settings.bot_cycle_interval_seconds)
    while True:
        try:
            await asyncio.to_thread(run_cycle)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - long-running task resilience
            print(f"bot cycle warning: {exc}")
        await asyncio.sleep(interval_seconds)


def bot_status() -> BotStatusResponse:
    task = getattr(app.state, "bot_task", None)
    return BotStatusResponse(running=task is not None and not task.done())


async def start_bot() -> BotStatusResponse:
    if not bot_status().running:
        app.state.bot_task = asyncio.create_task(_bot_loop())
    return bot_status()


async def pause_bot() -> BotStatusResponse:
    task = getattr(app.state, "bot_task", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    app.state.bot_task = None
    return bot_status()


app = FastAPI(
    title="Wes Get Rich API",
    version="0.1.0",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
async def start_price_sampler() -> None:
    settings = Settings()
    if getattr(settings, "auto_start_bot", False):
        app.state.bot_task = asyncio.create_task(_bot_loop())
    if settings.kraken_api_key and settings.kraken_api_secret:
        app.state.kraken_trade_sync_task = asyncio.create_task(_sync_kraken_trades_on_startup())
    if settings.enable_price_sampler:
        app.state.price_sampler_task = asyncio.create_task(_price_sampler_loop())


@app.on_event("shutdown")
async def stop_price_sampler() -> None:
    await pause_bot()

    trade_sync_task = getattr(app.state, "kraken_trade_sync_task", None)
    if trade_sync_task:
        trade_sync_task.cancel()
        with suppress(asyncio.CancelledError):
            await trade_sync_task

    task = getattr(app.state, "price_sampler_task", None)
    if not task:
        return

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@app.get("/bot/status", response_model=BotStatusResponse)
def bot_status_endpoint() -> BotStatusResponse:
    return bot_status()


@app.post("/bot/start", response_model=BotStatusResponse)
async def start_bot_endpoint() -> BotStatusResponse:
    return await start_bot()


@app.post("/bot/pause", response_model=BotStatusResponse)
async def pause_bot_endpoint() -> BotStatusResponse:
    return await pause_bot()


@app.get("/market/price", response_model=MarketPriceResponse)
def market_price(asset_symbol: str = Query(default="BTC")) -> MarketPriceResponse:
    normalized = _normalize_asset(asset_symbol)
    settings = Settings()
    
    try:
        # Try Kraken first
        price_chf = _build_kraken_service(settings).fetch_spot_price_usd(pair=_kraken_pair(settings))
    except KrakenServiceError:
        # Fall back to CoinGecko
        try:
            from .services.coingecko.service import fetch_current_price
            price_chf = fetch_current_price(asset_symbol=normalized, vs_currency="usd")
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Price unavailable: {str(e)}") from e
    
    return MarketPriceResponse(asset_symbol=normalized, price_chf=price_chf)


@app.get("/kraken/balance", response_model=KrakenBalanceResponse)
def kraken_balance() -> KrakenBalanceResponse:
    settings = Settings()
    service = _build_kraken_service(settings)

    try:
        balances = service.fetch_balances()
    except KrakenServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return KrakenBalanceResponse(
        live_trading_enabled=settings.live_trading_enabled,
        balances=balances,
    )


class SyncKrakenLedgerResponse(BaseModel):
    synced_count: int
    errors: list[str]


@app.post("/kraken/sync-ledger", response_model=SyncKrakenLedgerResponse)
def sync_kraken_ledger() -> SyncKrakenLedgerResponse:
    """Fetch deposit/withdrawal history from Kraken and sync to database."""
    settings = Settings()
    service = _build_kraken_service(settings)
    
    try:
        entries = service.fetch_ledger_entries()
    except KrakenServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    
    conn = get_connection(settings.dsn)
    synced_count = 0
    errors: list[str] = []
    
    try:
        # Get existing transactions to avoid duplicates
        existing_rows = list_transactions(conn, limit=10000)
        existing_refs = {row.get("notes") for row in existing_rows if row.get("notes", "").startswith("kraken:")}
        
        for entry in entries:
            ref_key = f"kraken:{entry.ref_id}"
            if ref_key in existing_refs:
                continue  # Already synced
            
            # Convert asset code to standard symbol (ZUSD -> USD, XXBT -> BTC)
            asset_symbol = entry.asset
            if asset_symbol.startswith("Z"):
                asset_symbol = asset_symbol[1:]  # ZUSD -> USD, ZEUR -> EUR
            elif asset_symbol.startswith("X"):
                asset_symbol = asset_symbol[1:]  # XXBT -> BTC
            
            try:
                create_transaction(
                    conn,
                    platform_name="kraken",
                    asset_symbol=asset_symbol,
                    action=entry.entry_type.upper(),
                    quantity_btc=entry.amount,
                    unit_price_usd=0.0,
                    fee_usd=entry.fee,
                    status="CLOSED",
                    transaction_at=entry.timestamp,
                    strategy_tag="kraken-sync",
                    notes=ref_key,
                )
                synced_count += 1
            except Exception as e:
                errors.append(f"Failed to sync {entry.ref_id}: {str(e)}")
    finally:
        conn.close()
    
    return SyncKrakenLedgerResponse(synced_count=synced_count, errors=errors)


class SyncKrakenTradesResponse(BaseModel):
    synced_count: int
    skipped_count: int
    errors: list[str]


@app.post("/kraken/sync-trades", response_model=SyncKrakenTradesResponse)
def sync_kraken_trades() -> SyncKrakenTradesResponse:
    settings = Settings()
    try:
        return SyncKrakenTradesResponse(**_sync_kraken_trades_to_db(settings))
    except KrakenServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _sync_kraken_trades_to_db(settings: Settings) -> dict[str, object]:
    """Fetch trade history from Kraken and sync BUY/SELL transactions to database."""
    service = _build_kraken_service(settings)

    result = service._request_private("/0/private/TradesHistory")

    trades = result.get("trades", {})
    conn = get_connection(settings.dsn)
    synced_count = 0
    skipped_count = 0
    errors: list[str] = []

    try:
        existing_rows = list_transactions(conn, limit=10000)
        existing_refs = {
            row.get("notes")
            for row in existing_rows
            if (row.get("notes") or "").startswith("kraken-trade:")
        }

        for trade_id, trade in trades.items():
            ref_key = f"kraken-trade:{trade_id}"
            if ref_key in existing_refs:
                skipped_count += 1
                continue

            try:
                action = "BUY" if trade["type"] == "buy" else "SELL"
                price = float(trade["price"])
                cost = float(trade["cost"])
                fee = float(trade["fee"])
                vol = float(trade["vol"])
                traded_at = datetime.fromtimestamp(float(trade["time"]), tz=timezone.utc)

                create_transaction(
                    conn,
                    platform_name="kraken",
                    asset_symbol="BTC",
                    action=action,
                    quantity_btc=vol,
                    unit_price_usd=price,
                    fee_usd=fee,
                    status="OPEN" if action == "BUY" else "CLOSED",
                    transaction_at=traded_at,
                    strategy_tag="kraken-sync",
                    notes=ref_key,
                )
                synced_count += 1
            except Exception as e:
                errors.append(f"Failed to sync trade {trade_id}: {str(e)}")
    finally:
        conn.close()

    return {"synced_count": synced_count, "skipped_count": skipped_count, "errors": errors}


@app.post("/strategy/samples/collect", response_model=CollectSampleResponse)
def collect_strategy_sample(asset_symbol: str = Query(default="BTC")) -> CollectSampleResponse:
    _normalize_asset(asset_symbol)
    settings = Settings()
    return _collect_and_store_sample(settings)


@app.get("/strategy/history", response_model=StrategyHistoryResponse)
def strategy_history(
    asset_symbol: str = Query(default="BTC"),
    hours: int = Query(default=24, ge=1, le=168),
    source: str | None = Query(default=None),
) -> StrategyHistoryResponse:
    normalized = _normalize_asset(asset_symbol)
    settings = Settings()
    selected_source = (source or settings.strategy_history_source).lower()

    if selected_source == "kraken":
        try:
            samples = _fetch_kraken_history_for_hours(settings, hours)
        except KrakenServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return StrategyHistoryResponse(
            asset_symbol=normalized,
            source="kraken",
            interval_minutes=max(1, settings.kraken_history_interval_minutes),
            samples=samples,
        )

    if selected_source != "db":
        raise HTTPException(status_code=400, detail="source must be either 'db' or 'kraken'")

    conn = get_connection(settings.dsn)
    try:
        rows = list_price_samples(conn, asset_symbol=normalized, hours=hours)
    finally:
        conn.close()

    return StrategyHistoryResponse(
        asset_symbol=normalized,
        source="db",
        interval_minutes=5,
        samples=[
            PriceSampleItem(sampled_at=row.sampled_at, price_chf=row.price_usd, source=row.source)
            for row in rows
        ],
    )


@app.get("/strategy/metrics", response_model=StrategyMetricsResponse)
def strategy_metrics(
    asset_symbol: str = Query(default="BTC"),
    hours: int | None = Query(default=None, ge=1, le=168),
) -> StrategyMetricsResponse:
    normalized = _normalize_asset(asset_symbol)
    settings = Settings()
    window_hours = hours or settings.strategy_metrics_window_hours

    conn = get_connection(settings.dsn)
    try:
        hourly = get_hourly_metrics(conn, asset_symbol=normalized, hours=window_hours)
    finally:
        conn.close()

    if not hourly:
        return StrategyMetricsResponse(
            asset_symbol=normalized,
            source="db",
            generated_at=datetime.now(timezone.utc),
            window_hours=window_hours,
            current_price_chf=None,
            min_price_chf=None,
            max_price_chf=None,
            avg_price_chf=None,
            change_window_pct=None,
            hourly=[],
        )

    min_price = min(h.min_price_usd for h in hourly)
    max_price = max(h.max_price_usd for h in hourly)
    avg_price = sum(h.avg_price_usd for h in hourly) / len(hourly)
    current_price = hourly[-1].last_price_usd
    first_price = hourly[0].last_price_usd
    change_window_pct = ((current_price - first_price) / first_price) * 100 if first_price > 0 else None

    return StrategyMetricsResponse(
        asset_symbol=normalized,
        source="db",
        generated_at=datetime.now(timezone.utc),
        window_hours=window_hours,
        current_price_chf=current_price,
        min_price_chf=min_price,
        max_price_chf=max_price,
        avg_price_chf=avg_price,
        change_window_pct=change_window_pct,
        hourly=[
            HourlyMetricItem(
                hour_start=h.hour_start,
                sample_count=h.sample_count,
                min_price_chf=h.min_price_usd,
                max_price_chf=h.max_price_usd,
                avg_price_chf=h.avg_price_usd,
                last_price_chf=h.last_price_usd,
            )
            for h in hourly
        ],
    )


@app.get("/binance/price", response_model=BinancePriceResponse)
def binance_price(symbol: str = Query(default="BTCUSDT")) -> BinancePriceResponse:
    settings = Settings()
    service = _build_binance_service(settings)

    try:
        price = service.get_symbol_price(symbol)
        return BinancePriceResponse(symbol=symbol.upper(), price=price)
    except BinanceServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/binance/order", response_model=BinanceOrderResponse)
def binance_order(payload: BinanceOrderRequest) -> BinanceOrderResponse:
    if payload.symbol.upper() != "BTCUSDT":
        raise HTTPException(
            status_code=400,
            detail="Only BTCUSDT is supported by the current BTC transaction schema.",
        )

    settings = Settings()
    service = _build_binance_service(settings)

    try:
        raw = service.place_market_order(
            symbol=payload.symbol,
            side=payload.side,
            quantity=payload.quantity,
            quote_order_qty=payload.quote_order_qty,
            test_order=payload.test_order,
        )
    except BinanceServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    executed_qty = _to_float(Decimal(raw["executedQty"])) if "executedQty" in raw else None
    cumm_quote_qty = _to_float(Decimal(raw["cummulativeQuoteQty"])) if "cummulativeQuoteQty" in raw else None

    avg_price = None
    if executed_qty and cumm_quote_qty and executed_qty > 0:
        avg_price = cumm_quote_qty / executed_qty

    recorded_transaction_id: int | None = None
    if payload.persist_transaction:
        if payload.test_order:
            raise HTTPException(
                status_code=400,
                detail="Cannot persist a Binance test order. Set test_order=false.",
            )

        if not executed_qty or not avg_price:
            raise HTTPException(
                status_code=400,
                detail="Order has no executed quantity or average price to persist.",
            )

        conn = get_connection(settings.dsn)
        try:
            recorded_transaction_id = create_transaction(
                conn,
                platform_name=payload.platform_name,
                asset_symbol="BTC",
                action=payload.side,
                quantity_btc=executed_qty,
                unit_price_usd=avg_price,
                fee_usd=0,
                status="OPEN" if payload.side == "BUY" else "CLOSED",
                transaction_at=payload.transaction_at or datetime.now(timezone.utc),
                strategy_tag=payload.strategy_tag,
                notes=payload.notes,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            conn.close()

    return BinanceOrderResponse(
        symbol=payload.symbol.upper(),
        side=payload.side,
        test_order=payload.test_order,
        order_id=raw.get("orderId"),
        status=raw.get("status"),
        executed_qty=executed_qty,
        cummulative_quote_qty=cumm_quote_qty,
        average_price=avg_price,
        recorded_transaction_id=recorded_transaction_id,
    )


@app.post("/kraken/order", response_model=KrakenOrderResponse)
def kraken_order(payload: KrakenOrderRequest) -> KrakenOrderResponse:
    settings = Settings()
    service = _build_kraken_service(settings)
    pair = _kraken_pair(settings)

    if payload.quantity_btc is None and payload.quote_order_qty is None:
        raise HTTPException(
            status_code=400,
            detail="Either quantity_btc or quote_order_qty must be provided.",
        )

    if payload.quantity_btc is not None and payload.quote_order_qty is not None:
        raise HTTPException(
            status_code=400,
            detail="Provide only one of quantity_btc or quote_order_qty.",
        )

    if not settings.live_trading_enabled and not payload.validate_only:
        raise HTTPException(
            status_code=403,
            detail="LIVE_TRADING_ENABLED is false. Refusing live Kraken order.",
        )

    side = payload.side.upper()

    try:
        spot_price = service.fetch_spot_price_usd(pair=pair)
    except KrakenServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    order_quantity = payload.quantity_btc
    quote_order_qty = payload.quote_order_qty
    if order_quantity is None and quote_order_qty is None:
        raise HTTPException(status_code=400, detail="Unable to determine valid order quantity.")

    if order_quantity is None and quote_order_qty is not None:
        order_quantity = quote_order_qty / spot_price

    if order_quantity is None or order_quantity <= 0:
        raise HTTPException(status_code=400, detail="Unable to determine valid order quantity.")

    try:
        raw = service.place_market_order(
            pair=pair,
            side=side,
            volume=order_quantity,
            quote_volume=quote_order_qty,
            validate_only=payload.validate_only,
        )
    except KrakenServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    recorded_transaction_id: int | None = None
    if payload.persist_transaction:
        if payload.validate_only:
            raise HTTPException(
                status_code=400,
                detail="Cannot persist a validate_only Kraken order. Set validate_only=false.",
            )

        conn = get_connection(settings.dsn)
        try:
            recorded_transaction_id = create_transaction(
                conn,
                platform_name=payload.platform_name,
                asset_symbol="BTC",
                action=side,
                quantity_btc=order_quantity,
                unit_price_usd=spot_price,
                fee_usd=0,
                status="OPEN" if side == "BUY" else "CLOSED",
                transaction_at=payload.transaction_at or datetime.now(timezone.utc),
                strategy_tag=payload.strategy_tag,
                notes=payload.notes or "Kraken market order placed; fill details may differ from estimate.",
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            conn.close()

    descr = raw.get("descr") or {}
    txid = raw.get("txid") or []
    if isinstance(txid, str):
        txid = [txid]

    return KrakenOrderResponse(
        pair=pair,
        side=side,
        validate_only=payload.validate_only,
        order_description=descr.get("order"),
        txid=txid,
        estimated_price_chf=spot_price,
        estimated_quantity_btc=order_quantity,
        recorded_transaction_id=recorded_transaction_id,
    )


@app.post("/transactions", response_model=TransactionCreateResponse, status_code=201)
def create_transaction_endpoint(payload: TransactionCreateRequest) -> TransactionCreateResponse:
    settings = Settings()
    conn = get_connection(settings.dsn)

    unit_price_chf = _pick_quote_value(payload.unit_price_chf, payload.unit_price_usd, default=None)
    fee_chf = _pick_quote_value(payload.fee_chf, payload.fee_usd)
    realized_pnl_chf = _pick_quote_value(
        payload.realized_pnl_chf,
        payload.realized_pnl_usd,
        default=None,
    )

    # For BUY/SELL, unit_price is required
    if payload.action in ("BUY", "SELL") and (unit_price_chf is None or unit_price_chf <= 0):
        raise HTTPException(status_code=400, detail="unit_price_chf or unit_price_usd must be provided and > 0 for BUY/SELL")

    try:
        transaction_id = create_transaction(
            conn,
            platform_name=payload.platform_name,
            asset_symbol=payload.asset_symbol.upper(),
            action=payload.action,
            quantity_btc=payload.quantity_btc,
            unit_price_usd=unit_price_chf or 0.0,
            fee_usd=fee_chf,
            status=payload.status,
            transaction_at=payload.transaction_at,
            strategy_tag=payload.strategy_tag,
            notes=payload.notes,
            paired_buy_transaction_id=payload.paired_buy_transaction_id,
            realized_pnl_usd=realized_pnl_chf,
        )
        return TransactionCreateResponse(id=transaction_id)
    except Exception as exc:  # pragma: no cover - defensive boundary for API errors
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@app.get("/transactions", response_model=list[TransactionItem])
def list_transactions_endpoint(limit: int = Query(default=100, ge=1, le=1000)) -> list[TransactionItem]:
    settings = Settings()
    conn = get_connection(settings.dsn)
    current_price_chf: float | None = None

    try:
        current_price_chf = _build_kraken_service(settings).fetch_spot_price_usd(pair=_kraken_pair(settings))
    except KrakenServiceError:
        current_price_chf = None

    try:
        rows = list_transactions(conn, limit=limit)
        items: list[TransactionItem] = []
        for row in rows:
            quantity_btc = _to_float(row["quantity_btc"]) or 0.0
            unit_price_chf = _to_float(row["unit_price_usd"]) or 0.0
            fee_chf = _to_float(row["fee_usd"]) or 0.0
            realized_pnl_chf = _to_float(row["realized_pnl_usd"])
            pnl_now_chf, profitability_status, profitability_color = _profitability_for_transaction(
                action=row["action"],
                status=row["status"],
                quantity_btc=quantity_btc,
                unit_price_chf=unit_price_chf,
                fee_chf=fee_chf,
                realized_pnl_chf=realized_pnl_chf,
                current_price_chf=current_price_chf,
            )

            items.append(
                TransactionItem(
                    id=row["id"],
                    platform_name=row["platform_name"],
                    asset_symbol=row["asset_symbol"],
                    action=row["action"],
                    quantity_btc=quantity_btc,
                    unit_price_chf=unit_price_chf,
                    fee_chf=fee_chf,
                    realized_pnl_chf=realized_pnl_chf,
                    unit_price_usd=unit_price_chf,
                    fee_usd=fee_chf,
                    paired_buy_transaction_id=row["paired_buy_transaction_id"],
                    realized_pnl_usd=realized_pnl_chf,
                    status=row["status"],
                    transaction_at=row["transaction_at"],
                    strategy_tag=row["strategy_tag"],
                    notes=row["notes"],
                    current_price_chf=current_price_chf,
                    unrealized_pnl_chf=pnl_now_chf,
                    profitability_status=profitability_status,
                    profitability_color=profitability_color,
                    executed_at=row["executed_at"],
                    created_at=row["created_at"],
                )
            )
        return items
    finally:
        conn.close()


@app.get("/portfolio/metrics", response_model=PortfolioMetricsResponse)
def portfolio_metrics(asset_symbol: str = Query(default="BTC")) -> PortfolioMetricsResponse:
    normalized = _normalize_asset(asset_symbol)
    settings = Settings()
    conn = get_connection(settings.dsn)
    exchange_fee_rate = _get_effective_exchange_fee_rate(settings)
    
    try:
        # Try Kraken first
        current_price = _build_kraken_service(settings).fetch_spot_price_usd(pair=_kraken_pair(settings))
    except KrakenServiceError:
        # Fall back to CoinGecko
        try:
            from .services.coingecko.service import fetch_current_price
            current_price = fetch_current_price(asset_symbol=normalized, vs_currency="usd")
        except Exception as e:
            current_price = None

    try:
        rows = list_transactions(conn, limit=1000)
    finally:
        conn.close()

    from .db import BuyPosition

    total_invested = _compute_open_invested(rows)
    total_realized_profit = 0.0
    total_realized_loss = 0.0
    total_fees_paid = 0.0
    gross_unrealized_pnl = 0.0
    fee_adjusted_unrealized_pnl = 0.0
    expected_exit_fees = 0.0
    open_positions: list[OpenPositionMetrics] = []
    
    cash_balance_chf = _compute_cash_balance(rows)
    live_btc_balance = 0.0
    try:
        live_balances = _build_kraken_service(settings).fetch_balances()
        live_cash_balance = _extract_live_cash_balance(live_balances)
        if live_cash_balance is not None:
            cash_balance_chf = live_cash_balance
        live_btc_balance = _extract_live_btc_balance(live_balances)
    except KrakenServiceError:
        pass

    for row in rows:
        total_fees_paid += float(row["fee_usd"] or 0)
        if row["action"] == "SELL" and row["status"] == "CLOSED":
            realized_pnl = float(row["realized_pnl_usd"] or 0)
            if realized_pnl >= 0:
                total_realized_profit += realized_pnl
            else:
                total_realized_loss += abs(realized_pnl)

        if row["action"] != "BUY":
            continue

        quantity_btc = float(row["quantity_btc"])
        unit_price_usd = float(row["unit_price_usd"])
        fee_usd = float(row["fee_usd"])
        cost_basis = (quantity_btc * unit_price_usd) + fee_usd
        if row["status"] != "CLOSED":
            position = BuyPosition(
                id=row["id"],
                quantity_btc=quantity_btc,
                unit_price_usd=unit_price_usd,
                fee_usd=fee_usd,
            )
            fee_adj = calculate_fee_adjusted_pnl(position, current_price, exchange_fee_rate)

            current_value = quantity_btc * current_price
            gross_pnl = current_value - cost_basis
            gross_unrealized_pnl += gross_pnl
            fee_adjusted_unrealized_pnl += fee_adj.net_pnl_chf
            expected_exit_fees += fee_adj.expected_sell_fee_chf

            open_positions.append(
                OpenPositionMetrics(
                    transaction_id=row["id"],
                    quantity_btc=quantity_btc,
                    cost_basis_chf=cost_basis,
                    current_value_chf=current_value,
                    gross_pnl_chf=gross_pnl,
                    fee_adjusted_pnl=FeeAdjustedPnLResponse(
                        gross_pnl_chf=fee_adj.gross_pnl_chf,
                        expected_sell_fee_chf=fee_adj.expected_sell_fee_chf,
                        net_pnl_chf=fee_adj.net_pnl_chf,
                        fee_adjusted_pnl_pct=fee_adj.fee_adjusted_pnl_pct,
                        break_even_price_chf=fee_adj.break_even_price_chf,
                    ),
                )
            )

    return PortfolioMetricsResponse(
        asset_symbol=normalized,
        current_price_chf=current_price,
        generated_at=datetime.now(timezone.utc),
        exchange_fee_rate=exchange_fee_rate,
        total_invested_chf=total_invested,
        total_realized_profit_chf=total_realized_profit,
        total_realized_loss_chf=total_realized_loss,
        gross_unrealized_pnl_chf=gross_unrealized_pnl,
        fee_adjusted_unrealized_pnl_chf=fee_adjusted_unrealized_pnl,
        total_fees_paid_chf=total_fees_paid,
        expected_exit_fees_chf=expected_exit_fees,
        open_positions=open_positions,
        cash_balance_chf=cash_balance_chf,
        live_btc_balance=live_btc_balance,
        live_btc_value_chf=live_btc_balance * current_price,
        total_portfolio_value_chf=cash_balance_chf + (live_btc_balance * current_price),
    )


# ============================================================================
# SIMULATION / BACKTEST ENDPOINTS
# ============================================================================


@app.post("/simulations", status_code=201, response_model=SimulationMetricsResponse)
def run_simulation_endpoint(payload: SimulationCreateRequest) -> SimulationMetricsResponse:
    """Run a new backtest simulation of the trend-v1 strategy."""
    settings = Settings()
    conn = get_connection(settings.dsn)
    
    try:
        # Convert parameters to dict for the backtest service
        parameters = {
            "wallet_fraction_per_trade": payload.parameters.wallet_fraction_per_trade,
            "max_open_positions": payload.parameters.max_open_positions,
            "min_minutes_between_trades": payload.parameters.min_minutes_between_trades,
            "take_profit_pct": payload.parameters.take_profit_pct,
            "stop_loss_pct": payload.parameters.stop_loss_pct,
            "dynamic_stop_loss_atr_multiplier": payload.parameters.dynamic_stop_loss_atr_multiplier,
            "trend_short_window_hours": payload.parameters.trend_short_window_hours,
            "trend_long_window_hours": payload.parameters.trend_long_window_hours,
            "bearish_exit_min_cycles": payload.parameters.bearish_exit_min_cycles,
            "enable_bearish_exit": payload.parameters.enable_bearish_exit,
            "exchange_fee_rate": _get_effective_exchange_fee_rate(settings),
        }
        
        metrics_dict = run_simulation(
            conn=conn,
            simulation_name=payload.simulation_name,
            asset_symbol=payload.asset_symbol.upper(),
            start_at=payload.start_at,
            end_at=payload.end_at,
            initial_wallet=payload.initial_wallet,
            parameters=parameters,
        )
        
        return SimulationMetricsResponse(**metrics_dict)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        conn.close()


@app.get("/simulations", response_model=list[SimulationItem])
def list_simulations_endpoint(limit: int = Query(default=50, ge=1, le=500)) -> list[SimulationItem]:
    """List all simulations."""
    settings = Settings()
    conn = get_connection(settings.dsn)
    
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    s.id, s.name, s.asset_symbol, s.start_at, s.end_at, s.initial_wallet,
                    m.total_return_pct, m.win_rate_pct, m.crash_guard_activations,
                    s.created_at
                FROM simulations s
                INNER JOIN simulation_metrics m ON s.id = m.simulation_id
                ORDER BY s.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        
        items = [
            SimulationItem(
                simulation_id=row[0],
                name=row[1],
                asset_symbol=row[2],
                start_at=row[3],
                end_at=row[4],
                initial_wallet=float(row[5]),
                total_return_pct=float(row[6]) if row[6] is not None else 0.0,
                win_rate_pct=float(row[7]) if row[7] is not None else 0.0,
                crash_guard_activations=row[8] if row[8] is not None else 0,
                created_at=row[9],
            )
            for row in rows
        ]
        return items
    finally:
        conn.close()


@app.get("/simulations/{simulation_id}", response_model=SimulationResultsResponse)
def get_simulation_endpoint(simulation_id: int) -> SimulationResultsResponse:
    """Fetch detailed results of a simulation including all transactions and trigger rules."""
    settings = Settings()
    conn = get_connection(settings.dsn)
    
    try:
        # Fetch simulation metadata
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, asset_symbol, start_at, end_at, initial_wallet, parameters, created_at
                FROM simulations
                WHERE id = %s
                """,
                (simulation_id,),
            )
            sim_row = cur.fetchone()
        
        if not sim_row:
            raise HTTPException(status_code=404, detail=f"Simulation {simulation_id} not found")
        
        # Fetch metrics
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT total_buys, total_sells, realized_pnl, unrealized_pnl_at_end,
                       total_return_pct, win_rate_pct, crash_guard_activations, computed_at
                FROM simulation_metrics
                WHERE simulation_id = %s
                """,
                (simulation_id,),
            )
            metrics_row = cur.fetchone()
        
        if not metrics_row:
            raise HTTPException(status_code=404, detail=f"Metrics for simulation {simulation_id} not found")
        
        # Fetch transactions
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, action, quantity, unit_price, fee, trigger_rule, realized_pnl, simulated_at
                FROM simulation_transactions
                WHERE simulation_id = %s
                ORDER BY simulated_at ASC
                """,
                (simulation_id,),
            )
            trans_rows = cur.fetchall()
        
        transactions = [
            SimulationTransactionResponse(
                id=row[0],
                action=row[1],
                quantity=float(row[2]),
                unit_price=float(row[3]),
                fee=float(row[4]),
                trigger_rule=row[5],
                realized_pnl=float(row[6]) if row[6] is not None else None,
                simulated_at=row[7],
            )
            for row in trans_rows
        ]
        
        metrics = SimulationMetricsResponse(
            total_buys=metrics_row[0],
            total_sells=metrics_row[1],
            realized_pnl=float(metrics_row[2]),
            unrealized_pnl_at_end=float(metrics_row[3]),
            total_return_pct=float(metrics_row[4]),
            win_rate_pct=float(metrics_row[5]),
            crash_guard_activations=metrics_row[6],
        )
        
        return SimulationResultsResponse(
            simulation_id=sim_row[0],
            name=sim_row[1],
            asset_symbol=sim_row[2],
            start_at=sim_row[3],
            end_at=sim_row[4],
            initial_wallet=float(sim_row[5]),
            parameters=sim_row[6],
            metrics=metrics,
            transactions=transactions,
            computed_at=metrics_row[7],
        )
    finally:
        conn.close()


class DataAvailabilityResponse(BaseModel):
    asset_symbol: str
    first_available: datetime
    last_available: datetime
    total_records: int


@app.get("/data-availability/{asset_symbol}", response_model=DataAvailabilityResponse)
def get_data_availability_endpoint(asset_symbol: str) -> DataAvailabilityResponse:
    """Get the range of available price data for an asset."""
    settings = Settings()
    conn = get_connection(settings.dsn)
    
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    MIN(sampled_at) as first_available,
                    MAX(sampled_at) as last_available,
                    COUNT(*) as total_records
                FROM price_samples
                WHERE asset_symbol = %s
                """,
                (asset_symbol,),
            )
            row = cur.fetchone()
        
        if not row or row[0] is None:
            raise HTTPException(
                status_code=404,
                detail=f"No price data available for {asset_symbol}"
            )
        
        return DataAvailabilityResponse(
            asset_symbol=asset_symbol,
            first_available=row[0],
            last_available=row[1],
            total_records=row[2],
        )
    finally:
        conn.close()


class DeleteSimulationResponse(BaseModel):
    success: bool
    message: str


@app.delete("/simulations/{simulation_id}", response_model=DeleteSimulationResponse)
def delete_simulation_endpoint(simulation_id: int) -> DeleteSimulationResponse:
    """Delete a simulation and all its associated data."""
    settings = Settings()
    conn = get_connection(settings.dsn)
    
    try:
        with conn.cursor() as cur:
            # Check if simulation exists
            cur.execute("SELECT id FROM simulations WHERE id = %s", (simulation_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail=f"Simulation {simulation_id} not found")
            
            # Delete associated metrics
            cur.execute("DELETE FROM simulation_metrics WHERE simulation_id = %s", (simulation_id,))
            
            # Delete associated transactions
            cur.execute("DELETE FROM simulation_transactions WHERE simulation_id = %s", (simulation_id,))
            
            # Delete simulation
            cur.execute("DELETE FROM simulations WHERE id = %s", (simulation_id,))
        
        conn.commit()
        return DeleteSimulationResponse(success=True, message=f"Simulation {simulation_id} deleted successfully")
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        conn.close()


class BackfillPriceDataRequest(BaseModel):
    asset_symbol: str = Field(default="BTC", description="BTC or ETH")
    start_at: datetime | None = Field(default=None, description="Start date (default: 365 days ago)")
    end_at: datetime | None = Field(default=None, description="End date (default: now)")
    interval_minutes: int = Field(default=5, description="OHLC interval: 1, 5, 15, 30, 60, 240, 1440")


class BackfillPriceDataResponse(BaseModel):
    asset_symbol: str
    start_at: datetime
    end_at: datetime
    interval_minutes: int
    samples_inserted: int
    message: str


@app.post("/backfill-price-data", response_model=BackfillPriceDataResponse)
def backfill_price_data_endpoint(request: BackfillPriceDataRequest) -> BackfillPriceDataResponse:
    """
    Backfill the database with historical price data from Kraken OHLC.
    
    Fetches OHLC prices from Kraken public API for the specified date range,
    then inserts them into the database.
    """
    settings = Settings()
    conn = get_connection(settings.dsn)
    
    try:
        # Set defaults
        end_at = request.end_at or datetime.now(timezone.utc)
        start_at = request.start_at or (end_at - timedelta(days=365))
        
        # Backfill from Kraken
        inserted = backfill_kraken_ohlc(
            conn=conn,
            asset_symbol=request.asset_symbol,
            start_at=start_at,
            end_at=end_at,
            interval_minutes=request.interval_minutes,
        )
        
        return BackfillPriceDataResponse(
            asset_symbol=request.asset_symbol,
            start_at=start_at,
            end_at=end_at,
            interval_minutes=request.interval_minutes,
            samples_inserted=inserted,
            message=f"Successfully inserted {inserted} price samples from Kraken",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        conn.close()


