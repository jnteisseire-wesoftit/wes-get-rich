# wes-get-rich

Bitcoin auto-invest starter project with transaction tracking, profit/loss calculations, and sell/hold decision support.

This repository gives you:

- A Python service that can place scheduled BTC buys (paper trading by default).
- A PostgreSQL schema that records every buy and sell transaction.
- Decision logic for `SELL`, `HOLD`, or `WATCH` based on take-profit and stop-loss thresholds.
- A Dockerized database image that initializes the required tables automatically.
- A FastAPI backend (`:2512`) with transaction create/list APIs.
- A Node.js frontend (`:2513`) with Transactions and Strategy pages.
- 5-minute BTC price sampling persisted in Postgres for strategy history.

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

1. The app fetches current BTC/USD price from CoinGecko.
2. It records a `BUY` transaction for your configured dollar amount.
3. It reviews open buy positions and computes change percentage.
4. If change exceeds thresholds:
   - `SELL` when gain >= take profit
   - `SELL` when loss <= stop loss
   - otherwise `HOLD`
5. Sell transactions are linked back to original buy transactions and store realized PnL.

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
EXCHANGE_FEE_RATE=0.001
TAKE_PROFIT_PCT=5
STOP_LOSS_PCT=-3
STRATEGY_TAG=dca-v1
ENABLE_PRICE_SAMPLER=true
PRICE_SAMPLE_INTERVAL_SECONDS=300
STRATEGY_HISTORY_SOURCE=db
STRATEGY_METRICS_WINDOW_HOURS=24

BINANCE_BASE_URL=https://api.binance.com
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret

KRAKEN_BASE_URL=https://api.kraken.com
```

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

- This starter performs paper-trade style recording logic and does not place live exchange orders.
- Replace the pricing and execution layers before connecting to real money accounts.
- Add authentication, auditing, and secrets management for production.
