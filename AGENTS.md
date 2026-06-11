# AGENTS

This file defines roles and responsibilities for growing this project from BTC-only into a multi-crypto auto-invest platform.

## 1) Trader Agent

Purpose:
- Executes strategy cycles (buy/evaluate/sell decisions).

Responsibilities:
- Read market price for the configured asset.
- Place paper-trade buy records in the database.
- Evaluate open positions with strategy thresholds.
- Trigger sell actions when thresholds are hit.

Inputs:
- Current market price
- `TAKE_PROFIT_PCT`
- `STOP_LOSS_PCT`
- `BUY_BUDGET_USD`

Outputs:
- New `BUY` and `SELL` rows in `transactions`
- Console decision log (`SELL`, `HOLD`, `WATCH`)

## 2) Risk Agent

Purpose:
- Protect capital by enforcing limits and kill-switches.

Responsibilities:
- Reject buys when daily budget is exceeded.
- Pause trading after consecutive stop-loss events.
- Validate position sizing constraints.

Future fields to add:
- `daily_budget_usd`
- `max_open_positions`
- `max_drawdown_pct`

## 3) Portfolio Agent

Purpose:
- Track account state and performance over time.

Responsibilities:
- Compute realized PnL from closed positions.
- Compute unrealized PnL for open buys.
- Publish summary metrics per asset and globally.

Core metrics:
- Total invested
- Realized PnL
- Unrealized PnL
- Win rate

## 4) Data Agent

Purpose:
- Keep transaction history reliable and queryable.

Responsibilities:
- Maintain schema migrations.
- Validate transaction integrity.
- Detect missing links between sell rows and buy rows.

Integrity checks:
- No `SELL` without `paired_buy_transaction_id`
- No negative `quantity_btc`
- No open buy with duplicate close event

## 5) Expansion Agent (Multi-Crypto)

Purpose:
- Generalize BTC workflow to support ETH, SOL, and more.

Responsibilities:
- Parameterize asset symbol in strategy and execution.
- Ensure per-asset budgeting and risk limits.
- Add price providers per exchange or aggregator.

Implementation notes:
- Current schema already includes `asset_symbol`.
- App logic should be extended to loop over configured assets.

## Operating Rules

- Never place live orders without explicit production flag and tested exchange adapter.
- Every action must be persisted in `transactions`.
- Decision logic changes require a new `strategy_tag`.
- Any schema change must include migration and rollback steps.

## Engineering Conventions

- Isolate service Python code under `src/services/<service_name>/`.
- Each service folder must contain a dedicated implementation file named `service.py`.
- API and strategy layers should import service logic from these dedicated service files instead of embedding provider-specific code.
