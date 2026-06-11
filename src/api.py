import asyncio
from contextlib import suppress
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import Settings
from .db import (
    create_transaction,
    get_connection,
    get_hourly_metrics,
    insert_price_sample,
    list_price_samples,
    list_transactions,
)
from .services.binance.service import BinanceCredentials, BinanceService, BinanceServiceError
from .services.kraken.service import KrakenService, KrakenServiceError
from .services.market.service import fetch_btc_price_usd
from .strategy import FeeAdjustedPnL, calculate_fee_adjusted_pnl


class TransactionCreateRequest(BaseModel):
    platform_name: str = Field(min_length=2, max_length=50)
    asset_symbol: str = Field(min_length=2, max_length=20)
    action: Literal["BUY", "SELL"]
    quantity_btc: float = Field(gt=0)
    unit_price_usd: float = Field(gt=0)
    fee_usd: float = Field(ge=0, default=0)
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
    unit_price_usd: float
    fee_usd: float
    paired_buy_transaction_id: int | None
    realized_pnl_usd: float | None
    status: str
    transaction_at: datetime
    strategy_tag: str | None
    notes: str | None
    executed_at: datetime
    created_at: datetime


class MarketPriceResponse(BaseModel):
    asset_symbol: str
    price_usd: float


class BinancePriceResponse(BaseModel):
    symbol: str
    price: float


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


class PriceSampleItem(BaseModel):
    sampled_at: datetime
    price_usd: float
    source: str


class StrategyHistoryResponse(BaseModel):
    asset_symbol: str
    source: str
    interval_minutes: int
    samples: list[PriceSampleItem]


class HourlyMetricItem(BaseModel):
    hour_start: datetime
    sample_count: int
    min_price_usd: float
    max_price_usd: float
    avg_price_usd: float
    last_price_usd: float


class StrategyMetricsResponse(BaseModel):
    asset_symbol: str
    source: str
    generated_at: datetime
    window_hours: int
    current_price_usd: float | None
    min_price_usd: float | None
    max_price_usd: float | None
    avg_price_usd: float | None
    change_window_pct: float | None
    hourly: list[HourlyMetricItem]


class CollectSampleResponse(BaseModel):
    id: int
    asset_symbol: str
    source: str
    sampled_at: datetime
    price_usd: float


class FeeAdjustedPnLResponse(BaseModel):
    gross_pnl_usd: float
    expected_sell_fee_usd: float
    net_pnl_usd: float
    fee_adjusted_pnl_pct: float
    break_even_price_usd: float


class OpenPositionMetrics(BaseModel):
    transaction_id: int
    quantity_btc: float
    cost_basis_usd: float
    current_value_usd: float
    gross_pnl_usd: float
    fee_adjusted_pnl: FeeAdjustedPnLResponse


class PortfolioMetricsResponse(BaseModel):
    asset_symbol: str
    current_price_usd: float
    generated_at: datetime
    exchange_fee_rate: float
    total_invested_usd: float
    total_realized_profit_usd: float
    total_realized_loss_usd: float
    gross_unrealized_pnl_usd: float
    fee_adjusted_unrealized_pnl_usd: float
    total_fees_paid_usd: float
    expected_exit_fees_usd: float
    open_positions: list[OpenPositionMetrics]


def _to_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _build_binance_service(settings: Settings) -> BinanceService:
    creds = None
    if settings.binance_api_key and settings.binance_api_secret:
        creds = BinanceCredentials(
            api_key=settings.binance_api_key,
            api_secret=settings.binance_api_secret,
        )

    return BinanceService(base_url=settings.binance_base_url, credentials=creds)


def _build_kraken_service(settings: Settings) -> KrakenService:
    return KrakenService(base_url=settings.kraken_base_url)


def _normalize_asset(asset_symbol: str) -> str:
    normalized = asset_symbol.upper()
    if normalized != "BTC":
        raise HTTPException(status_code=400, detail="Only BTC is supported for now")
    return normalized


def _collect_and_store_sample(settings: Settings) -> CollectSampleResponse:
    sampled_at = datetime.now(timezone.utc)

    source = "kraken"
    try:
        price_usd = _build_kraken_service(settings).fetch_spot_price_usd(pair="XBTUSD")
    except KrakenServiceError:
        source = "coingecko"
        price_usd = fetch_btc_price_usd()

    conn = get_connection(settings.dsn)
    try:
        sample_id = insert_price_sample(
            conn,
            asset_symbol="BTC",
            source=source,
            price_usd=price_usd,
            sampled_at=sampled_at,
        )
    finally:
        conn.close()

    return CollectSampleResponse(
        id=sample_id,
        asset_symbol="BTC",
        source=source,
        sampled_at=sampled_at,
        price_usd=price_usd,
    )


async def _price_sampler_loop() -> None:
    settings = Settings()
    sleep_seconds = max(60, settings.price_sample_interval_seconds)

    while True:
        try:
            _collect_and_store_sample(settings)
        except Exception as exc:  # pragma: no cover - long-running task resilience
            print(f"price sampler warning: {exc}")

        await asyncio.sleep(sleep_seconds)


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
    if settings.enable_price_sampler:
        app.state.price_sampler_task = asyncio.create_task(_price_sampler_loop())


@app.on_event("shutdown")
async def stop_price_sampler() -> None:
    task = getattr(app.state, "price_sampler_task", None)
    if not task:
        return

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@app.get("/market/price", response_model=MarketPriceResponse)
def market_price(asset_symbol: str = Query(default="BTC")) -> MarketPriceResponse:
    normalized = _normalize_asset(asset_symbol)

    price_usd = fetch_btc_price_usd()
    return MarketPriceResponse(asset_symbol=normalized, price_usd=price_usd)


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
            samples = _build_kraken_service(settings).fetch_ohlc_close_prices(
                pair="XBTUSD",
                interval_minutes=5,
            )
        except KrakenServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        cutoff = datetime.now(timezone.utc).timestamp() - (hours * 3600)
        filtered = [s for s in samples if s.sampled_at.timestamp() >= cutoff]
        return StrategyHistoryResponse(
            asset_symbol=normalized,
            source="kraken",
            interval_minutes=5,
            samples=[
                PriceSampleItem(sampled_at=s.sampled_at, price_usd=s.price_usd, source="kraken")
                for s in filtered
            ],
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
            PriceSampleItem(sampled_at=row.sampled_at, price_usd=row.price_usd, source=row.source)
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
            current_price_usd=None,
            min_price_usd=None,
            max_price_usd=None,
            avg_price_usd=None,
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
        current_price_usd=current_price,
        min_price_usd=min_price,
        max_price_usd=max_price,
        avg_price_usd=avg_price,
        change_window_pct=change_window_pct,
        hourly=[
            HourlyMetricItem(
                hour_start=h.hour_start,
                sample_count=h.sample_count,
                min_price_usd=h.min_price_usd,
                max_price_usd=h.max_price_usd,
                avg_price_usd=h.avg_price_usd,
                last_price_usd=h.last_price_usd,
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


@app.post("/transactions", response_model=TransactionCreateResponse, status_code=201)
def create_transaction_endpoint(payload: TransactionCreateRequest) -> TransactionCreateResponse:
    settings = Settings()
    conn = get_connection(settings.dsn)

    try:
        transaction_id = create_transaction(
            conn,
            platform_name=payload.platform_name,
            asset_symbol=payload.asset_symbol.upper(),
            action=payload.action,
            quantity_btc=payload.quantity_btc,
            unit_price_usd=payload.unit_price_usd,
            fee_usd=payload.fee_usd,
            status=payload.status,
            transaction_at=payload.transaction_at,
            strategy_tag=payload.strategy_tag,
            notes=payload.notes,
            paired_buy_transaction_id=payload.paired_buy_transaction_id,
            realized_pnl_usd=payload.realized_pnl_usd,
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

    try:
        rows = list_transactions(conn, limit=limit)
        items: list[TransactionItem] = []
        for row in rows:
            items.append(
                TransactionItem(
                    id=row["id"],
                    platform_name=row["platform_name"],
                    asset_symbol=row["asset_symbol"],
                    action=row["action"],
                    quantity_btc=_to_float(row["quantity_btc"]),
                    unit_price_usd=_to_float(row["unit_price_usd"]),
                    fee_usd=_to_float(row["fee_usd"]),
                    paired_buy_transaction_id=row["paired_buy_transaction_id"],
                    realized_pnl_usd=_to_float(row["realized_pnl_usd"]),
                    status=row["status"],
                    transaction_at=row["transaction_at"],
                    strategy_tag=row["strategy_tag"],
                    notes=row["notes"],
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
    current_price = fetch_btc_price_usd()

    try:
        rows = list_transactions(conn, limit=1000)
    finally:
        conn.close()

    from .db import BuyPosition

    total_invested = 0.0
    total_realized_profit = 0.0
    total_realized_loss = 0.0
    total_fees_paid = 0.0
    gross_unrealized_pnl = 0.0
    fee_adjusted_unrealized_pnl = 0.0
    expected_exit_fees = 0.0
    open_positions: list[OpenPositionMetrics] = []

    for row in rows:
        if row["action"] != "BUY":
            continue

        quantity_btc = float(row["quantity_btc"])
        unit_price_usd = float(row["unit_price_usd"])
        fee_usd = float(row["fee_usd"])
        cost_basis = (quantity_btc * unit_price_usd) + fee_usd
        total_invested += cost_basis
        total_fees_paid += fee_usd

        if row["status"] == "CLOSED":
            realized_pnl = float(row["realized_pnl_usd"] or 0)
            if realized_pnl >= 0:
                total_realized_profit += realized_pnl
            else:
                total_realized_loss += abs(realized_pnl)
        else:
            position = BuyPosition(
                id=row["id"],
                quantity_btc=quantity_btc,
                unit_price_usd=unit_price_usd,
                fee_usd=fee_usd,
            )
            fee_adj = calculate_fee_adjusted_pnl(position, current_price, settings.exchange_fee_rate)

            current_value = quantity_btc * current_price
            gross_pnl = current_value - cost_basis
            gross_unrealized_pnl += gross_pnl
            fee_adjusted_unrealized_pnl += fee_adj.net_pnl_usd
            expected_exit_fees += fee_adj.expected_sell_fee_usd

            open_positions.append(
                OpenPositionMetrics(
                    transaction_id=row["id"],
                    quantity_btc=quantity_btc,
                    cost_basis_usd=cost_basis,
                    current_value_usd=current_value,
                    gross_pnl_usd=gross_pnl,
                    fee_adjusted_pnl=FeeAdjustedPnLResponse(
                        gross_pnl_usd=fee_adj.gross_pnl_usd,
                        expected_sell_fee_usd=fee_adj.expected_sell_fee_usd,
                        net_pnl_usd=fee_adj.net_pnl_usd,
                        fee_adjusted_pnl_pct=fee_adj.fee_adjusted_pnl_pct,
                        break_even_price_usd=fee_adj.break_even_price_usd,
                    ),
                )
            )

    return PortfolioMetricsResponse(
        asset_symbol=normalized,
        current_price_usd=current_price,
        generated_at=datetime.now(timezone.utc),
        exchange_fee_rate=settings.exchange_fee_rate,
        total_invested_usd=total_invested,
        total_realized_profit_usd=total_realized_profit,
        total_realized_loss_usd=total_realized_loss,
        gross_unrealized_pnl_usd=gross_unrealized_pnl,
        fee_adjusted_unrealized_pnl_usd=fee_adjusted_unrealized_pnl,
        total_fees_paid_usd=total_fees_paid,
        expected_exit_fees_usd=expected_exit_fees,
        open_positions=open_positions,
    )

