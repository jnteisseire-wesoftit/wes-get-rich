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
- `WALLET_FRACTION_PER_TRADE`
- `MAX_OPEN_POSITIONS`
- `MIN_MINUTES_BETWEEN_TRADES`
- `TAKE_PROFIT_PCT`
- `STOP_LOSS_PCT`
- `DYNAMIC_STOP_LOSS_ATR_MULTIPLIER`
- `TREND_SHORT_WINDOW_HOURS`
- `TREND_LONG_WINDOW_HOURS`

Outputs:
- New `BUY` and `SELL` rows in `transactions`
- Console decision log (`SELL`, `HOLD`, `WATCH`)

## 2) Risk Agent

Purpose:
- Protect capital by enforcing limits and resolving cash shortfalls before giving up.

Responsibilities:
- Block buys when `open_positions >= MAX_OPEN_POSITIONS`.
- Block buys when cooldown has not elapsed (`time_since_last_buy < MIN_MINUTES_BETWEEN_TRADES`).
- Block buys when crash guard is active (current decline exceeds historical 95th percentile over the crash guard window).
- When a buy signal fires but `free_cash < buy_budget`: find the open position with the highest `fee_adjusted_pnl_pct` where `fee_adjusted_pnl > 0`; sell it to free cash, then proceed with the buy. Only block the buy if no such candidate exists.
- Gate take-profit and bearish-exit sells on `fee_adjusted_pnl > 0`; stop-loss sells are never gated.

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

## 6) Backtest Agent (Simulation)

Purpose:
- Validate strategy rules against historical price data before running live.

Responsibilities:
- Accept a named simulation with a start date, end date, initial wallet, and full set of strategy parameters.
- Replay `price_samples` chronologically from `start_at` to `end_at`, simulating one cycle every `MIN_MINUTES_BETWEEN_TRADES`.
- Apply the full strategy at each step: trend detection, crash guard, position sizing, sell triggers, buy signal — identical logic to the live Trader Agent.
- Record every simulated transaction with the rule that triggered it (e.g. `TAKE_PROFIT`, `STOP_LOSS`, `BEARISH_EXIT`, `CRASH_GUARD_BLOCK`, `TREND_BUY`, `REINVEST`).
- Compute and persist final summary metrics on completion.
- Save the full parameter set alongside the simulation so runs are reproducible and comparable.

DB schema (new tables required):

```
simulations
  id, name (unique), asset_symbol, start_at, end_at,
  initial_wallet, parameters (JSON), created_at

simulation_transactions
  id, simulation_id → simulations,
  action (BUY|SELL), quantity, unit_price, fee,
  paired_buy_id → simulation_transactions,
  realized_pnl, trigger_rule, simulated_at, created_at

simulation_metrics
  simulation_id → simulations (PK),
  total_buys, total_sells,
  realized_pnl, unrealized_pnl_at_end,
  total_return_pct, win_rate_pct,
  crash_guard_activations, computed_at
```

Inputs:
- `simulation_name` — unique label for this run
- `start_at`, `end_at` — time window to replay
- `initial_wallet` — starting cash (clean slate, no prior positions)
- All strategy parameters (same set as Trader Agent)

Outputs:
- Rows in `simulations`, `simulation_transactions`, `simulation_metrics`
- Console summary of final metrics on completion

## Strategy Rules

### Cash Management

- `free_cash = net_deposits + realized_pnl − cost_basis_of_all_open_positions`
- `total_wallet = net_deposits + realized_pnl + unrealized_pnl`
- `buy_budget = total_wallet × WALLET_FRACTION_PER_TRADE` (default `0.10`, i.e. 1/10)
- A BUY is only placed when `free_cash >= buy_budget`.

### Cycle Execution Order

Each strategy cycle runs in this exact sequence. Only one meaningful action occurs per cycle.

```
Step 1 — Evaluate all open positions for sell triggers
  (take-profit, stop-loss, bearish exit — see Sell Triggers)
  → If any SELL was executed → stop, skip buy evaluation this cycle

Step 2 — Evaluate buy signal (only reached if no sell fired in Step 1)
  Conditions: trend is BULLISH
          AND open_positions < MAX_OPEN_POSITIONS
          AND time_since_last_buy >= MIN_MINUTES_BETWEEN_TRADES
          AND crash guard is not active
    → free_cash >= buy_budget?
        YES → place BUY
        NO  → find best candidate to sell-to-reinvest (see below)
                → found → SELL it, then place BUY in same cycle (atomic)
                → none qualifies → skip, do nothing
```

### Sell-to-Reinvest Candidate Selection

When cash is needed to fund a new buy, pick the open position with the **highest `fee_adjusted_pnl_pct`** that satisfies `fee_adjusted_pnl > 0` (net profit after both buy and sell fees is positive).

### Sell Triggers

| Trigger | Condition | Fee gate |
|---|---|---|
| **Reinvest** | Need cash for a new buy | `fee_adjusted_pnl > 0` required |
| **Take profit** | `change_pct >= TAKE_PROFIT_PCT` | `fee_adjusted_pnl > 0` required |
| **Stop-loss** | `change_pct <= dynamic_stop_loss_pct` | **No gate** — sell regardless |
| **Bearish exit** | Trend has been BEARISH for `BEARISH_EXIT_MIN_CYCLES` consecutive cycles and position is in profit | `fee_adjusted_pnl > 0` required |

### Market Trend Detection

- Compute a **short-term MA** (default: last 6 hourly candles) and a **long-term MA** (default: last 24 hourly candles) from `price_samples`.
- `BULLISH` when short MA > long MA.
- `BEARISH` when short MA < long MA.
- `NEUTRAL` when equal or insufficient data.
- No BUY is placed on `BEARISH` or `NEUTRAL`.

### Crash Guard

- At each cycle, compute the price change over the last `4 × MIN_MINUTES_BETWEEN_TRADES` minutes (the **crash guard window**) from `price_samples`.
- With the default 1440 min cooldown, the crash guard window is **5 760 minutes (4 days)**.
- Compare that decline against the **95th percentile of all negative moves** of the same window length, drawn from the last 90 days of historical data in `price_samples`.
- If the current decline is worse than that percentile → crash guard is **active** → block all buys this cycle.
- Re-evaluated fresh every cycle — no forced lockout beyond the current cycle; the trend signal will keep blocking buys naturally during a prolonged crash.

### Dynamic Stop-Loss

- Measure recent market volatility: average of `(hourly_high − hourly_low) / hourly_avg` over the last 24 candles.
- `dynamic_stop_loss_pct = −(avg_range_pct × DYNAMIC_STOP_LOSS_ATR_MULTIPLIER)`
- This widens the stop-loss during volatile periods to avoid being stopped out on normal price noise.
- A hard floor (`STOP_LOSS_PCT`) is enforced so the loss never exceeds the configured maximum.

### Configurable Parameters

| Parameter | Default | Description |
|---|---|---|
| `WALLET_FRACTION_PER_TRADE` | `0.10` | Fraction of total wallet per buy |
| `MAX_OPEN_POSITIONS` | `10` | Cap on concurrent open positions |
| `MIN_MINUTES_BETWEEN_TRADES` | `2880` | Cooldown between buys (minutes, default 48 h) |
| `TAKE_PROFIT_PCT` | `10.0` | Sell when net gain after fees reaches this % |
| `STOP_LOSS_PCT` | `-4.0` | Hard floor for stop-loss % |
| `DYNAMIC_STOP_LOSS_ATR_MULTIPLIER` | `2.0` | Volatility multiplier for dynamic stop |
| `TREND_SHORT_WINDOW_HOURS` | `6` | Hours for short-term MA |
| `TREND_LONG_WINDOW_HOURS` | `24` | Hours for long-term MA |
| `BEARISH_EXIT_MIN_CYCLES` | `4` | Consecutive bearish cycles required when bearish exits are enabled |

## Operating Rules

- Never place live orders without explicit production flag and tested exchange adapter.
- Every action must be persisted in `transactions`.
- Decision logic changes require a new `strategy_tag`.
- Any schema change must include migration and rollback steps.

## Current Runtime Controls

- The dashboard trading bot is paused by default.
- `POST /bot/start` starts the dashboard-managed strategy loop.
- `POST /bot/pause` cancels future strategy cycles.
- `GET /bot/status` reports whether the loop is running.
- The cycle interval is controlled by `BOT_CYCLE_INTERVAL_SECONDS` (default 300 seconds).
- Bearish exits are disabled by default with `ENABLE_BEARISH_EXIT=false`; positions hold through bearish trends unless take-profit or stop-loss rules trigger.
- Portfolio cash uses the live Kraken CHF balance when `Query Funds` permission is available, with local transaction-ledger fallback.
- `Available Cash to Invest` is buying power; `Current Holdings Value` is open BTC market value and excludes cash.
- Backtest PnL includes both buy and sell fees. Backtest transactions are stored separately from live/paper transactions.

### Verification Commands

```bash
PYTHONPATH=. .venv/bin/pytest tests/unit tests/integration -v
docker compose up --build --force-recreate --no-deps --pull always -d
```

## Engineering Conventions

- Isolate service Python code under `src/services/<service_name>/`.
- Each service folder must contain a dedicated implementation file named `service.py`.
- API and strategy layers should import service logic from these dedicated service files instead of embedding provider-specific code.

## Coding Approach

### Test-Driven Development (TDD) — MANDATORY ⚠️

**All implementation work MUST follow strict TDD discipline. No exceptions.**

Every single feature, fix, or refactor — from line 1 — requires tests first, then code. This is non-negotiable.

TDD cycle (required before ANY production code is written):

```
1. Write a failing unit test that captures the expected behaviour
2. Write the minimum code to make the test pass
3. Refactor if needed — tests must stay green
```

**Rules:**
- ✅ **ALWAYS write tests first.** Green test fails before implementation exists.
- ✅ **NO production code without a test that justifies it.** Every function, every branch.
- ✅ **Tests live under `tests/unit/`** for pure logic and **`tests/integration/`** for DB or API behaviour.
- ✅ **Each new strategy function** (trend detection, crash guard, stop-loss, etc.) must have its own dedicated test file.
- ✅ **Each new DB query function** must have an integration test using a real test database connection.
- ✅ **Tests must cover:** happy path, edge cases (empty data, boundary values), and failure modes.
- ✅ **Run full test suite before committing:** `pytest tests/unit/ tests/integration/ -v`

**Violations:** If production code is added without corresponding tests, it will be rejected. No excuses.

### Test Naming Convention

```
test_<function>_<scenario>_<expected_outcome>

Examples:
  test_evaluate_trend_bullish_when_short_ma_above_long_ma
  test_crash_guard_blocks_buy_when_decline_exceeds_95th_percentile
  test_compute_dynamic_stop_loss_widens_during_high_volatility
  test_run_cycle_skips_buy_when_crash_guard_active
```

### Change Discipline

- Strategy logic changes require a new `strategy_tag` value.
- Schema changes require a numbered migration file under `docker/db/init/` with a matching rollback comment.
- No behaviour change is merged without a test that would have caught the regression.

---

## Development Plan

Implement the strategy rules defined in this file in strict TDD order. Complete each phase fully (tests green) before moving to the next.

The new `strategy_tag` for all cycles produced by this implementation is `trend-v1`.

---

### Phase 1 — Config: add new parameters

**File:** `src/config.py`

Remove `buy_budget_usd`. Add the following fields with their defaults:

```python
wallet_fraction_per_trade: float = float(os.getenv("WALLET_FRACTION_PER_TRADE", "0.10"))
max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "10"))
min_minutes_between_trades: int = int(os.getenv("MIN_MINUTES_BETWEEN_TRADES", "1440"))
take_profit_pct: float = float(os.getenv("TAKE_PROFIT_PCT", "5.0"))
stop_loss_pct: float = float(os.getenv("STOP_LOSS_PCT", "-3.0"))
dynamic_stop_loss_atr_multiplier: float = float(os.getenv("DYNAMIC_STOP_LOSS_ATR_MULTIPLIER", "1.5"))
trend_short_window_hours: int = int(os.getenv("TREND_SHORT_WINDOW_HOURS", "6"))
trend_long_window_hours: int = int(os.getenv("TREND_LONG_WINDOW_HOURS", "24"))
bearish_exit_min_cycles: int = int(os.getenv("BEARISH_EXIT_MIN_CYCLES", "2"))
```

No tests required for config dataclass fields — covered implicitly by later tests.

---

### Phase 2 — Strategy: pure functions (no DB, no I/O)

**File:** `src/strategy.py`
**Test files:** one file per function under `tests/unit/`

Implement each function below. Write the failing tests first, then the implementation.

#### 2a. `TrendSignal` enum

```python
class TrendSignal(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
```

#### 2b. `evaluate_trend`

```python
def evaluate_trend(
    hourly_metrics: list[HourlyMetric],
    short_window: int,
    long_window: int,
) -> TrendSignal
```

- Returns `NEUTRAL` when `len(hourly_metrics) < 2`.
- Short MA = mean of `avg_price_usd` over the last `min(short_window, len)` entries.
- Long MA = mean of `avg_price_usd` over the last `min(long_window, len)` entries.
- Returns `BULLISH` when short MA > long MA, `BEARISH` when short MA < long MA, `NEUTRAL` when equal.

**Test file:** `tests/unit/test_evaluate_trend.py`

Required tests:
- `test_evaluate_trend_bullish_when_short_ma_above_long_ma`
- `test_evaluate_trend_bearish_when_short_ma_below_long_ma`
- `test_evaluate_trend_neutral_when_insufficient_data`
- `test_evaluate_trend_neutral_when_mas_are_equal`

#### 2c. `compute_dynamic_stop_loss`

```python
def compute_dynamic_stop_loss(
    hourly_metrics: list[HourlyMetric],
    base_stop_loss_pct: float,
    atr_multiplier: float,
) -> float
```

- Uses last 24 entries (or all if fewer).
- `avg_range_pct = mean((high − low) / avg × 100)` per candle.
- `dynamic = −(avg_range_pct × atr_multiplier)`.
- Returns `min(base_stop_loss_pct, dynamic)` — the more negative value wins.
- Returns `base_stop_loss_pct` when `hourly_metrics` is empty.

**Test file:** `tests/unit/test_compute_dynamic_stop_loss.py`

Required tests:
- `test_compute_dynamic_stop_loss_widens_during_high_volatility`
- `test_compute_dynamic_stop_loss_uses_base_when_volatility_is_low`
- `test_compute_dynamic_stop_loss_returns_base_when_no_data`

#### 2d. `is_crash_guard_active`

```python
def is_crash_guard_active(
    price_samples: list[PriceSample],
    window_minutes: int,
    lookback_days: int = 90,
) -> bool
```

- `window_minutes = 4 × MIN_MINUTES_BETWEEN_TRADES` (caller computes and passes this).
- Computes the price change over the most recent `window_minutes` of samples.
- Collects all historical changes of the same window length from the last `lookback_days`.
- Computes the 95th percentile of negative moves from that history.
- Returns `True` when the current decline is worse (more negative) than that percentile.
- Returns `False` when there is insufficient history to compute a percentile.

**Test file:** `tests/unit/test_crash_guard.py`

Required tests:
- `test_crash_guard_active_when_decline_exceeds_95th_percentile`
- `test_crash_guard_inactive_when_decline_is_normal`
- `test_crash_guard_inactive_when_insufficient_history`
- `test_crash_guard_inactive_when_no_current_window_data`

#### 2e. `compute_wallet`

```python
def compute_wallet(
    net_deposits: float,
    realized_pnl: float,
    open_positions_cost_basis: float,
    open_positions_current_value: float,
) -> tuple[float, float]  # (free_cash, total_wallet)
```

- `free_cash = net_deposits + realized_pnl − open_positions_cost_basis`
- `total_wallet = net_deposits + realized_pnl + (open_positions_current_value − open_positions_cost_basis)`
- Both values can be negative if losses exceed deposits.

**Test file:** `tests/unit/test_compute_wallet.py`

Required tests:
- `test_compute_wallet_free_cash_excludes_invested_capital`
- `test_compute_wallet_total_includes_unrealized_gains`
- `test_compute_wallet_handles_zero_open_positions`

#### 2f. `find_reinvest_candidate`

```python
def find_reinvest_candidate(
    positions: list[BuyPosition],
    current_price: float,
    exchange_fee_rate: float,
) -> BuyPosition | None
```

- Computes `fee_adjusted_pnl` for each position using `calculate_fee_adjusted_pnl`.
- Filters to positions where `fee_adjusted_pnl > 0`.
- Returns the position with the highest `fee_adjusted_pnl_pct`, or `None` if none qualify.

**Test file:** `tests/unit/test_find_reinvest_candidate.py`

Required tests:
- `test_find_reinvest_candidate_returns_most_profitable`
- `test_find_reinvest_candidate_returns_none_when_all_at_loss`
- `test_find_reinvest_candidate_returns_none_when_no_positions`
- `test_find_reinvest_candidate_excludes_positions_where_fee_exceeds_profit`

#### 2g. Update `evaluate_position`

Add `trend: TrendSignal` and `bearish_cycles: int` parameters.

New bearish-exit trigger: when `bearish_cycles >= BEARISH_EXIT_MIN_CYCLES` and `fee_adjusted_pnl > 0`, return `Decision.SELL`.

The dynamic stop-loss value is computed by the caller and passed in as `stop_loss_pct`.

**Test file:** update `tests/unit/test_entry_strategy.py`

Required new tests:
- `test_evaluate_position_sells_on_bearish_exit_after_min_cycles`
- `test_evaluate_position_holds_when_bearish_cycles_below_threshold`
- `test_evaluate_position_stop_loss_ignores_fee_gate`

---

### Phase 3 — DB layer: new query functions

**File:** `src/db.py`
**Test files:** `tests/integration/`

#### 3a. `get_last_buy_time`

```python
def get_last_buy_time(
    conn: psycopg.Connection,
    asset_symbol: str,
) -> datetime | None
```

- Returns the `transaction_at` of the most recent `BUY` row for the asset, or `None`.

**Test:** `tests/integration/test_get_last_buy_time.py`

#### 3b. `get_wallet_summary`

```python
@dataclass
class WalletSummary:
    net_deposits: float
    realized_pnl: float
    open_cost_basis: float

def get_wallet_summary(
    conn: psycopg.Connection,
    asset_symbol: str,
) -> WalletSummary
```

- `net_deposits` = sum of DEPOSIT `quantity_btc` − sum of WITHDRAWAL `quantity_btc` (both with `fee_usd` deducted).
- `realized_pnl` = sum of `realized_pnl_usd` from all SELL rows.
- `open_cost_basis` = sum of `(quantity_btc × unit_price_usd) + fee_usd` for all OPEN BUY rows.

**Test:** `tests/integration/test_get_wallet_summary.py`

#### 3c. `get_price_samples_window`

```python
def get_price_samples_window(
    conn: psycopg.Connection,
    asset_symbol: str,
    from_minutes_ago: int,
    lookback_days: int = 90,
) -> list[PriceSample]
```

- Returns all `price_samples` rows within the last `lookback_days` days, ordered by `sampled_at ASC`.
- Used by the crash guard to compute the historical distribution.

**Test:** `tests/integration/test_get_price_samples_window.py`

---

### Phase 4 — Main cycle rewrite

**File:** `src/main.py`
**Test file:** `tests/unit/test_main_cycle.py`

Rewrite `run_cycle()` to follow the Cycle Execution Order defined in Strategy Rules:

```
1. Fetch current price and hourly metrics from DB.
2. Evaluate trend (evaluate_trend).
3. Evaluate open positions for sell triggers in order:
   a. Dynamic stop-loss (compute_dynamic_stop_loss → evaluate_position)
   b. Take-profit (evaluate_position)
   c. Bearish exit (evaluate_position with bearish_cycles count)
   If any SELL executed → stop cycle here.
4. Compute wallet summary (get_wallet_summary).
5. Compute free_cash and buy_budget (compute_wallet).
6. Check buy conditions:
   - trend == BULLISH
   - open_positions < MAX_OPEN_POSITIONS
   - time_since_last_buy >= MIN_MINUTES_BETWEEN_TRADES
   - crash guard not active (is_crash_guard_active)
7. If all conditions met:
   a. free_cash >= buy_budget → insert_buy
   b. free_cash < buy_budget → find_reinvest_candidate → close_with_sell then insert_buy
   c. No candidate → skip
```

Update `FakeSettings` in `tests/unit/test_main_cycle.py` to include all new config fields.

Required new tests:
- `test_run_cycle_skips_buy_when_trend_is_bearish`
- `test_run_cycle_skips_buy_when_max_positions_reached`
- `test_run_cycle_skips_buy_when_cooldown_not_elapsed`
- `test_run_cycle_skips_buy_when_crash_guard_active`
- `test_run_cycle_sells_to_reinvest_when_no_free_cash`
- `test_run_cycle_skips_buy_when_no_reinvest_candidate`
- `test_run_cycle_skips_buy_after_sell_fires_in_same_cycle`

---

### Phase 5 — DB migration: simulation tables

**File:** `docker/db/init/005_add_simulation_tables.sql`

```sql
-- rollback: DROP TABLE simulation_metrics; DROP TABLE simulation_transactions; DROP TABLE simulations;

CREATE TABLE IF NOT EXISTS simulations (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    asset_symbol VARCHAR(20) NOT NULL,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    initial_wallet NUMERIC(18, 2) NOT NULL,
    parameters JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS simulation_transactions (
    id BIGSERIAL PRIMARY KEY,
    simulation_id BIGINT NOT NULL REFERENCES simulations(id) ON DELETE CASCADE,
    action VARCHAR(4) NOT NULL CHECK (action IN ('BUY', 'SELL')),
    quantity NUMERIC(24, 12) NOT NULL,
    unit_price NUMERIC(18, 2) NOT NULL,
    fee NUMERIC(18, 2) NOT NULL DEFAULT 0,
    paired_buy_id BIGINT NULL REFERENCES simulation_transactions(id),
    realized_pnl NUMERIC(18, 2) NULL,
    trigger_rule TEXT NOT NULL,
    simulated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS simulation_metrics (
    simulation_id BIGINT PRIMARY KEY REFERENCES simulations(id) ON DELETE CASCADE,
    total_buys INT NOT NULL,
    total_sells INT NOT NULL,
    realized_pnl NUMERIC(18, 2) NOT NULL,
    unrealized_pnl_at_end NUMERIC(18, 2) NOT NULL,
    total_return_pct NUMERIC(10, 4) NOT NULL,
    win_rate_pct NUMERIC(10, 4) NOT NULL,
    crash_guard_activations INT NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

### Phase 6 — Backtest service

**File:** `src/services/backtest/service.py`
**Test file:** `tests/integration/test_backtest_simulation.py`

Implement `run_simulation`:

```python
def run_simulation(
    conn: psycopg.Connection,
    simulation_name: str,
    asset_symbol: str,
    start_at: datetime,
    end_at: datetime,
    initial_wallet: float,
    parameters: dict,
) -> dict  # final metrics summary
```

Logic:
1. Insert a row into `simulations` with the given name and parameters JSON.
2. Load all `price_samples` for the asset between `start_at` and `end_at`.
3. Slice into steps of `MIN_MINUTES_BETWEEN_TRADES` minutes.
4. At each step, simulate the full strategy cycle using the same pure functions from Phase 2.
5. Write every BUY/SELL to `simulation_transactions` with the `trigger_rule` label.
6. After all steps, compute and write `simulation_metrics`.
7. Print a summary to console and return the metrics dict.

Required tests:
- `test_simulation_records_buys_on_bullish_trend`
- `test_simulation_records_sells_on_take_profit`
- `test_simulation_records_crash_guard_block_in_trigger_rule`
- `test_simulation_persists_parameters_with_name`
- `test_simulation_fails_on_duplicate_name`

---

### Phase 7 — Verification

After all phases are complete:

1. Run the full test suite: `pytest tests/unit/ tests/integration/ -v`
2. Rebuild and start the stack: `docker compose up --build --force-recreate --no-deps --pull always -d`
3. Verify the migration applied: connect to DB and confirm `simulations`, `simulation_transactions`, `simulation_metrics` tables exist.
4. Run one live cycle manually: `docker exec wes_get_rich_backend python3 -m src.main`
5. Confirm console output includes trend signal, crash guard status, and wallet summary.
