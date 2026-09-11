# wes-get-rich

Bitcoin auto-invest starter project with transaction tracking, profit/loss calculations, and sell/hold decision support.

This repository gives you:

- A Python service that can place scheduled BTC buys (paper trading by default).
- A PostgreSQL schema that records every buy and sell transaction.
- Decision logic for `SELL`, `HOLD`, or `WATCH` based on take-profit and stop-loss thresholds.
- A Dockerized database image that initializes the required tables automatically.
- A FastAPI backend (`:2512`) with transaction create/list APIs.
- A Node.js frontend (`:2513`) with Transactions, Strategy, and Simulations pages.
- 5-minute BTC price sampling persisted in Postgres for strategy history.
- A dashboard play/pause control for the trading bot; the bot starts paused.

## Project Structure

```text
.
├── AGENTS.md
├── docker
│   └── db
│       ├── Dockerfile
│       └── init
│           └── 001_schema.sql
├── docker-compose.yml
├── frontend
│   ├── Dockerfile
│   ├── index.html
│   ├── package.json
│   └── server.js
├── requirements.txt
└── src
	├── api.py
	├── config.py
	├── db.py
	├── main.py
	├── strategy.py
	└── services
		├── binance
		│   └── service.py
		└── market
			└── service.py
```

## How It Works

1. The app fetches current BTC/CHF price from **Kraken** (with CoinGecko as fallback).
2. Historical price data is backfilled from Kraken's public OHLC API.
3. It records a `BUY` transaction using the configured wallet fraction.
4. It reviews open buy positions and computes change percentage.
5. If change exceeds thresholds:
   - `SELL` when gain >= take profit
   - `SELL` when loss <= stop loss
   - otherwise `HOLD`
6. Sell transactions are linked back to original buy transactions and store realized PnL.

## Prerequisites

- Docker + Docker Compose
- Python 3.11+

## 1) Start Full Stack (DB + Backend + Frontend)

```bash
docker compose up -d
```

The Postgres container is built from `docker/db/Dockerfile` and runs schema creation from `docker/db/init/001_schema.sql`.

Service ports:

- Frontend: `http://localhost:2513`
- Backend API: `http://localhost:2512`

Network model:

- `backend_private` (internal network): only `backend` and `db` are attached.
- `app_public` (public app network): `frontend` and `backend` are attached.
- Database is not published to host ports, so only backend can access it.

## 2) Configure Environment

Create a `.env` file in the project root:

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=investor
DB_USER=investor
DB_PASSWORD=investor

ASSET_SYMBOL=BTC
BUY_BUDGET_USD=50
EXCHANGE_FEE_RATE=0.004
TAKE_PROFIT_PCT=7
STOP_LOSS_PCT=-4
WALLET_FRACTION_PER_TRADE=0.10
MAX_OPEN_POSITIONS=10
MIN_MINUTES_BETWEEN_TRADES=2880
DYNAMIC_STOP_LOSS_ATR_MULTIPLIER=2.0
TREND_SHORT_WINDOW_HOURS=6
TREND_LONG_WINDOW_HOURS=24
BEARISH_EXIT_MIN_CYCLES=4
ENABLE_BEARISH_EXIT=false
BUY_ENTRY_DISCOUNT_PCT=1.0
STRATEGY_TAG=dca-v1
ENABLE_PRICE_SAMPLER=true
PRICE_SAMPLE_INTERVAL_SECONDS=300
BOT_CYCLE_INTERVAL_SECONDS=300
STRATEGY_HISTORY_SOURCE=db
STRATEGY_METRICS_WINDOW_HOURS=24
KRAKEN_HISTORY_LOOKBACK_DAYS=90
KRAKEN_HISTORY_INTERVAL_MINUTES=5
LIVE_TRADING_ENABLED=false

BINANCE_BASE_URL=https://api.binance.com
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret

KRAKEN_BASE_URL=https://api.kraken.com
KRAKEN_TRADING_PAIR=XBTCHF
KRAKEN_API_KEY=your_kraken_api_key
KRAKEN_API_SECRET=your_kraken_api_secret
```

`LIVE_TRADING_ENABLED` is a safety guard and should stay `false` until you explicitly enable real order placement logic.
`BUY_ENTRY_DISCOUNT_PCT` controls how far below the recent average price BTC must be before the bot opens a new buy.
With `KRAKEN_TRADING_PAIR=XBTCHF`, the Kraken live order endpoint spends CHF balance instead of USD balance.

At startup, the backend synchronizes Kraken trade history idempotently when private API credentials are configured.
It continuously syncs Kraken OHLC history into `price_samples` at 5-minute cadence.
It backfills from the latest stored candle, or from the last 90 days when DB is empty.

The dashboard's **Available Cash to Invest** uses the live Kraken CHF balance when the API key has
the `Query Funds` permission. If that private endpoint is unavailable, it falls back to the local
transaction ledger. **Current Holdings Value** is the market value of open BTC positions and does not
include cash.

## 3) Install Dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 4) Backend API

OpenAPI and interactive docs:

- OpenAPI JSON: `http://localhost:2512/openapi.json`
- Swagger UI: `http://localhost:2512/docs`
- ReDoc: `http://localhost:2512/redoc`

Create a transaction:

```bash
curl -X POST http://localhost:2512/transactions \
	-H "Content-Type: application/json" \
	-d '{
		"platform_name": "kraken",
		"asset_symbol": "BTC",
		"action": "BUY",
		"quantity_btc": 0.001,
		"unit_price_usd": 68000,
		"fee_usd": 1.5,
		"status": "OPEN",
		"transaction_at": "2026-06-10T10:00:00Z",
		"strategy_tag": "manual-api"
	}'
```

`platform_name` and `transaction_at` are required for each transaction.

List past transactions:

```bash
curl "http://localhost:2512/transactions?limit=100"
```

Get current BTC price (used by frontend to compute live portfolio value and unrealized P/L):

```bash
curl "http://localhost:2512/market/price?asset_symbol=BTC"
```

Collect one BTC sample into DB immediately:

```bash
curl -X POST "http://localhost:2512/strategy/samples/collect?asset_symbol=BTC"
```

Get strategy history from DB samples (or `source=kraken` for direct exchange candles):

```bash
curl "http://localhost:2512/strategy/history?asset_symbol=BTC&hours=24&source=db"
```

Get hourly strategy metrics:

```bash
curl "http://localhost:2512/strategy/metrics?asset_symbol=BTC&hours=24"
```

Get Binance spot price:

```bash
curl "http://localhost:2512/binance/price?symbol=BTCUSDT"
```

Get Kraken account balances (requires Kraken API key/secret):

```bash
curl "http://localhost:2512/kraken/balance"
```

Synchronize Kraken trade history into the local transaction ledger:

```bash
curl -X POST "http://localhost:2512/kraken/sync-trades"
```

Control the dashboard-managed trading bot:

```bash
curl "http://localhost:2512/bot/status"
curl -X POST "http://localhost:2512/bot/start"
curl -X POST "http://localhost:2512/bot/pause"
```

The bot is paused by default. Starting it runs strategy cycles at `BOT_CYCLE_INTERVAL_SECONDS`.
Bearish exits are disabled by default; set `ENABLE_BEARISH_EXIT=true` to opt into them.

Place a Kraken market order:

```bash
curl -X POST http://localhost:2512/kraken/order \
	-H "Content-Type: application/json" \
	-d '{
		"side": "BUY",
		"quote_order_qty": 10,
		"validate_only": true,
		"persist_transaction": false
	}'
```

Set `validate_only=false` only after you are confident with the API key permissions and you want a real order to be sent. Keep `LIVE_TRADING_ENABLED=true` to allow the live path.
For `XBTCHF`, `quote_order_qty` is interpreted as CHF.

Place Binance market order (test order by default):

```bash
curl -X POST http://localhost:2512/binance/order \
	-H "Content-Type: application/json" \
	-d '{
		"symbol": "BTCUSDT",
		"side": "BUY",
		"quote_order_qty": 50,
		"test_order": true,
		"persist_transaction": false
	}'
```

## 8) Tests

Install test dependencies:

```bash
pip install -r requirements-dev.txt
```

Run all tests:

```bash
pytest
```

Run unit tests only:

```bash
pytest tests/unit
```

Run integration tests only:

```bash
pytest tests/integration
```

## 5) Frontend UI

Open:

```text
http://localhost:2513
```

The page lets you:

- Create a new transaction record
- View past transactions in a table
- Open `/strategy` to view hourly metrics and 5-minute BTC sample history
- Open `/simulations` to run and inspect historical backtests
- Start or pause the trading bot from the dashboard

## 6) Optional: Run One Invest Cycle Manually

```bash
python -m src.main
```

This executes one cycle:

- fetch price
- create one buy transaction
- evaluate open positions
- optionally create sell transactions
- print recommendation summary

## 7) Inspect Transactions via SQL

```sql
SELECT id, action, quantity_btc, unit_price_usd, fee_usd, realized_pnl_usd, executed_at
FROM transactions
ORDER BY id DESC;
```

For existing databases created before this change, apply the migration in:

- `docker/db/init/002_add_platform_and_transaction_at.sql`

## Notes

- Simulation PnL includes both buy and sell fees.
- Backtest trades are stored in `simulation_transactions`, separate from live/paper `transactions`.
- The dashboard cash metric represents buying power, while holdings value is displayed separately.
- This starter performs paper-trade style recording logic by default; live exchange orders require explicit configuration.
- Replace the pricing and execution layers before connecting to real money accounts.
- Add authentication, auditing, and secrets management for production.
