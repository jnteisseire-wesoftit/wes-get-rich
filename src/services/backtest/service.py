"""Backtest simulation service for the trend-v1 strategy."""
from datetime import datetime, timedelta
from dataclasses import dataclass
from bisect import bisect_left, bisect_right
import json
import psycopg

from src.db import PriceSample, HourlyMetric
from src.strategy import (
    TrendSignal,
    Decision,
    compute_dynamic_stop_loss,
    compute_wallet,
    evaluate_trend,
    evaluate_position,
    find_reinvest_candidate,
    is_crash_guard_active,
)


@dataclass
class SimulationMetrics:
    """Summary metrics from a completed simulation."""
    total_buys: int
    total_sells: int
    realized_pnl: float
    unrealized_pnl_at_end: float
    total_return_pct: float
    win_rate_pct: float
    crash_guard_activations: int


def _build_hourly_metrics(price_samples: list[PriceSample]) -> list[HourlyMetric]:
    by_hour: dict[datetime, list[float]] = {}
    for sample in price_samples:
        hour_start = sample.sampled_at.replace(minute=0, second=0, microsecond=0)
        by_hour.setdefault(hour_start, []).append(float(sample.price_chf))

    return [
        HourlyMetric(
            hour_start=hour_start,
            sample_count=len(prices),
            min_price_usd=min(prices),
            max_price_usd=max(prices),
            avg_price_usd=sum(prices) / len(prices),
            last_price_usd=prices[-1],
        )
        for hour_start, prices in sorted(by_hour.items())
    ]


def _compute_unrealized_pnl(open_buys: list[tuple[float, float, float, datetime, int]], final_price: float) -> float:
    cost_basis = sum(quantity * price + buy_fee for quantity, price, buy_fee, _, _ in open_buys)
    current_value = sum(quantity * final_price for quantity, _, _, _, _ in open_buys)
    return current_value - cost_basis


def _compute_net_trade_pnl(
    quantity: float,
    buy_price: float,
    buy_fee: float,
    sell_price: float,
    sell_fee: float,
) -> float:
    return (quantity * sell_price) - sell_fee - (quantity * buy_price) - buy_fee


def _should_exit_bearish(
    trend: TrendSignal,
    bearish_cycles: int,
    minimum_cycles: int,
    net_pnl: float,
    enabled: bool = False,
) -> bool:
    return (
        enabled
        and
        trend == TrendSignal.BEARISH
        and bearish_cycles >= minimum_cycles
        and net_pnl > 0
    )


def _samples_up_to(price_samples: list[PriceSample], sample_times: list[datetime], current_time: datetime) -> tuple[int, list[PriceSample]]:
    """Return the latest sample index and available samples using binary search."""
    sample_end = bisect_right(sample_times, current_time)
    return sample_end, price_samples[:sample_end]


def run_simulation(
    conn: psycopg.Connection,
    simulation_name: str,
    asset_symbol: str,
    start_at: datetime,
    end_at: datetime,
    initial_wallet: float,
    parameters: dict,
) -> dict:
    """
    Run a full backtest simulation of the trend-v1 strategy.
    
    Replays historical price data from start_at to end_at, executing the full
    strategy cycle at each step (every MIN_MINUTES_BETWEEN_TRADES).
    
    Args:
        conn: Database connection
        simulation_name: Unique name for this simulation
        asset_symbol: Asset to simulate (BTC, ETH, etc.)
        start_at: Start time for simulation
        end_at: End time for simulation
        initial_wallet: Starting cash for the simulation
        parameters: Full strategy parameters dict (with all required fields)
    
    Returns:
        Dict with final metrics (total_buys, total_sells, realized_pnl, etc.)
    
    Raises:
        ValueError: If simulation_name already exists or parameters are invalid
    """
    # Validate parameters
    required_params = [
        'wallet_fraction_per_trade',
        'max_open_positions',
        'min_minutes_between_trades',
        'take_profit_pct',
        'stop_loss_pct',
        'dynamic_stop_loss_atr_multiplier',
        'trend_short_window_hours',
        'trend_long_window_hours',
        'bearish_exit_min_cycles',
        'exchange_fee_rate',
    ]
    for param in required_params:
        if param not in parameters:
            raise ValueError(f"Missing required parameter: {param}")
    
    # Check if simulation already exists
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM simulations WHERE name = %s",
            (simulation_name,),
        )
        if cur.fetchone():
            raise ValueError(f"Simulation with name '{simulation_name}' already exists")
    
    # Insert simulation record
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO simulations (name, asset_symbol, start_at, end_at, initial_wallet, parameters)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (simulation_name, asset_symbol, start_at, end_at, initial_wallet, json.dumps(parameters)),
        )
        simulation_id = cur.fetchone()[0]
    conn.commit()
    
    # Fetch price samples for the entire period
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT sampled_at, price_usd, source
            FROM price_samples
            WHERE asset_symbol = %s
              AND sampled_at >= %s
              AND sampled_at <= %s
            ORDER BY sampled_at ASC
            """,
            (asset_symbol, start_at, end_at),
        )
        rows = cur.fetchall()
    
    price_samples = [
        PriceSample(sampled_at=row[0], price_usd=float(row[1]), source=row[2])
        for row in rows
    ]
    
    if not price_samples:
        raise ValueError(f"No price samples found for {asset_symbol} between {start_at} and {end_at}")
    
    # Adjust start_at to when data first becomes available
    first_sample = min(price_samples, key=lambda x: x.sampled_at).sampled_at
    last_sample = max(price_samples, key=lambda x: x.sampled_at).sampled_at
    
    if first_sample > start_at:
        print(f"⚠ Adjusting simulation start from {start_at} to {first_sample} (when data first available)")
        start_at = first_sample
    
    if last_sample < end_at:
        print(f"⚠ Adjusting simulation end from {end_at} to {last_sample} (last available data)")
        end_at = last_sample
    
    # === SIMULATION LOOP ===
    # Step every 5 minutes for granular trading opportunities
    sim_step_minutes = 5  # Always use 5-minute steps for simulation
    step = timedelta(minutes=sim_step_minutes)
    
    # Extract the min_minutes_between_trades for cooldown enforcement
    min_minutes_between_trades = parameters['min_minutes_between_trades']
    
    print(f"📊 Simulation: {simulation_name}")
    print(f"   Asset: {asset_symbol}, Period: {start_at.date()} to {end_at.date()}")
    print(f"   Price data: {len(price_samples)} samples")
    print(f"   Simulation step: {sim_step_minutes} minutes")
    print(f"   Min minutes between buys (cooldown): {min_minutes_between_trades}")
    print(f"   Max open positions: {parameters['max_open_positions']}")
    print(f"   Initial wallet: ${initial_wallet}")
    print()
    
    current_time = start_at
    sample_times = [sample.sampled_at for sample in price_samples]
    open_buys = []  # Track open buy positions: (quantity, unit_price, buy_fee, buy_time, buy_id)
    buy_id_counter = 1
    last_buy_time = None  # Track time of last buy for cooldown enforcement
    transactions = []  # (action, quantity, unit_price, fee, trigger_rule, realized_pnl, buy_id_if_sell)
    realized_pnl_total = 0.0
    crash_guard_activations = 0
    
    # Debug counters
    step_count = 0
    bearish_count = 0
    bearish_cycles = 0
    bullish_count = 0
    neutral_count = 0
    cooldown_count = 0
    crash_guard_count = 0
    position_limit_count = 0
    
    while current_time <= end_at:
        sample_end = bisect_right(sample_times, current_time)
        if sample_end == 0:
            current_time += step
            continue

        step_count += 1
        current_price = price_samples[sample_end - 1].price_chf
        
        # Compute trend from recent price history
        max_window_hours = max(
            parameters['trend_short_window_hours'],
            parameters['trend_long_window_hours'],
            24,
        )
        window_start = current_time - timedelta(hours=max_window_hours)
        window_start_index = bisect_left(sample_times, window_start, 0, sample_end)
        hourly_metrics = _build_hourly_metrics(price_samples[window_start_index:sample_end])
        
        # === EVALUATE TREND ===
        trend = evaluate_trend(
            hourly_metrics=hourly_metrics,
            short_window=parameters['trend_short_window_hours'],
            long_window=parameters['trend_long_window_hours'],
        )
        if trend == TrendSignal.BEARISH:
            bearish_cycles += 1
            bearish_count += 1
        else:
            bearish_cycles = 0
        
        # === EVALUATE OPEN POSITIONS FOR SELLS ===
        sell_executed = False
        
        if open_buys:
            dynamic_stop = compute_dynamic_stop_loss(
                hourly_metrics=hourly_metrics,
                base_stop_loss_pct=parameters['stop_loss_pct'],
                atr_multiplier=parameters['dynamic_stop_loss_atr_multiplier'],
            )
            
            # Check each open buy for sell triggers
            remaining_buys = []
            for buy_qty, buy_price, buy_fee, buy_time, buy_id in open_buys:
                change_pct = ((current_price - buy_price) / buy_price) * 100
                sell_fee = (buy_qty * current_price) * parameters['exchange_fee_rate']
                net_pnl = _compute_net_trade_pnl(
                    buy_qty,
                    buy_price,
                    buy_fee,
                    current_price,
                    sell_fee,
                )
                
                trigger_rule = None
                
                # Check stop-loss
                if change_pct <= dynamic_stop:
                    trigger_rule = "STOP_LOSS"
                
                # Check take-profit
                elif change_pct >= parameters['take_profit_pct'] and net_pnl > 0:
                    trigger_rule = "TAKE_PROFIT"
                
                elif _should_exit_bearish(
                    trend,
                    bearish_cycles,
                    parameters['bearish_exit_min_cycles'],
                    net_pnl,
                    parameters.get('enable_bearish_exit', False),
                ):
                    trigger_rule = "BEARISH_EXIT"
                
                if trigger_rule:
                    # Execute sell
                    transactions.append(("SELL", buy_qty, current_price, sell_fee, trigger_rule, net_pnl, buy_id, current_time))
                    realized_pnl_total += net_pnl
                    sell_executed = True
                else:
                    # Keep open
                    remaining_buys.append((buy_qty, buy_price, buy_fee, buy_time, buy_id))
            
            open_buys = remaining_buys
        
        if sell_executed:
            current_time += step
            continue
        
        # === EVALUATE BUY CONDITIONS ===
        if trend != TrendSignal.BULLISH:
            if trend == TrendSignal.NEUTRAL:
                neutral_count += 1
            current_time += step
            continue
        
        bullish_count += 1
        
        if len(open_buys) >= parameters['max_open_positions']:
            position_limit_count += 1
            current_time += step
            continue
        
        # Check cooldown: time since last buy
        if last_buy_time is not None and (current_time - last_buy_time) < timedelta(minutes=min_minutes_between_trades):
            cooldown_count += 1
            current_time += step
            continue

        # Crash guard is only relevant when a buy is otherwise eligible.
        if is_crash_guard_active(
            price_samples[:sample_end],
            4 * min_minutes_between_trades,
        ):
            crash_guard_activations += 1
            crash_guard_count += 1
            current_time += step
            continue
        
        # Compute wallet and buy budget
        cost_basis = sum(qty * price + buy_fee for qty, price, buy_fee, _, _ in open_buys)
        current_value = sum(qty * current_price for qty, _, _, _, _ in open_buys)
        unrealized = current_value - cost_basis
        
        free_cash = initial_wallet + realized_pnl_total - cost_basis
        total_wallet = initial_wallet + realized_pnl_total + unrealized
        buy_budget = total_wallet * parameters['wallet_fraction_per_trade']
        
        # === EXECUTE BUY ===
        if free_cash >= buy_budget:
            # Place buy
            buy_fee = buy_budget * parameters['exchange_fee_rate']
            buy_qty = (buy_budget - buy_fee) / current_price
            
            transactions.append(("BUY", buy_qty, current_price, buy_fee, "TREND_BUY", None, None, current_time))
            open_buys.append((buy_qty, current_price, buy_fee, current_time, buy_id_counter))
            last_buy_time = current_time  # Record time of this buy for cooldown enforcement
            buy_id_counter += 1
        
        current_time += step
    
    # === FINALIZE SIMULATION ===
    # Compute final metrics
    total_buys = len([t for t in transactions if t[0] == "BUY"])
    total_sells = len([t for t in transactions if t[0] == "SELL"])
    
    # Compute unrealized PnL at end
    final_price = price_samples[-1].price_chf
    unrealized_pnl_at_end = _compute_unrealized_pnl(open_buys, final_price)
    
    total_return_pct = ((initial_wallet + realized_pnl_total + unrealized_pnl_at_end) / initial_wallet) * 100 - 100
    
    # Win rate (sells with positive PnL / total sells)
    profitable_sells = len([t for t in transactions if t[0] == "SELL" and t[5] and t[5] > 0])
    win_rate_pct = (profitable_sells / total_sells * 100) if total_sells > 0 else 0.0
    
    # Persist transactions
    with conn.cursor() as cur:
        for action, qty, price, fee, trigger, pnl, buy_id, tx_time in transactions:
            cur.execute(
                """
                INSERT INTO simulation_transactions
                (simulation_id, action, quantity, unit_price, fee, trigger_rule, realized_pnl, simulated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (simulation_id, action, qty, price, fee, trigger, pnl, tx_time),
            )
    conn.commit()
    
    # Persist metrics
    metrics = SimulationMetrics(
        total_buys=total_buys,
        total_sells=total_sells,
        realized_pnl=realized_pnl_total,
        unrealized_pnl_at_end=unrealized_pnl_at_end,
        total_return_pct=total_return_pct,
        win_rate_pct=win_rate_pct,
        crash_guard_activations=crash_guard_activations,
    )
    
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO simulation_metrics
            (simulation_id, total_buys, total_sells, realized_pnl, unrealized_pnl_at_end,
             total_return_pct, win_rate_pct, crash_guard_activations)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (simulation_id, metrics.total_buys, metrics.total_sells, metrics.realized_pnl,
             metrics.unrealized_pnl_at_end, metrics.total_return_pct, metrics.win_rate_pct,
             metrics.crash_guard_activations),
        )
    conn.commit()
    
    print(f"Simulation complete: {simulation_name}")
    print(f"  Total steps: {step_count}")
    print(f"  Buys: {total_buys}, Sells: {total_sells}")
    print(f"  Realized PnL: CHF {metrics.realized_pnl:.2f}")
    print(f"  Unrealized PnL: CHF {metrics.unrealized_pnl_at_end:.2f}")
    print(f"  Total return: {metrics.total_return_pct:.2f}%")
    print(f"  Win rate: {metrics.win_rate_pct:.1f}%")
    print(f"  Crash guard activations: {metrics.crash_guard_activations}")
    print(f"  Trend analysis: Bullish={bullish_count}, Bearish={bearish_count}, Neutral={neutral_count}")
    print(f"  Buy blocks: Cooldown={cooldown_count}, Crash Guard={crash_guard_count}, Position Limit={position_limit_count}")
    
    return {
        "total_buys": metrics.total_buys,
        "total_sells": metrics.total_sells,
        "realized_pnl": metrics.realized_pnl,
        "unrealized_pnl_at_end": metrics.unrealized_pnl_at_end,
        "total_return_pct": metrics.total_return_pct,
        "win_rate_pct": metrics.win_rate_pct,
        "crash_guard_activations": metrics.crash_guard_activations,
    }
