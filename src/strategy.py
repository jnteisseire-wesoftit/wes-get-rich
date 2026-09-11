from dataclasses import dataclass
from enum import Enum
import statistics
from datetime import datetime

from .db import BuyPosition, HourlyMetric, PriceSample


class Decision(str, Enum):
    SELL = "SELL"
    HOLD = "HOLD"
    WATCH = "WATCH"


class EntryDecision(str, Enum):
    BUY = "BUY"
    SKIP = "SKIP"


class TrendSignal(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass
class PositionDecision:
    buy_id: int
    decision: Decision
    change_pct: float


@dataclass
class FeeAdjustedPnL:
    gross_pnl_chf: float
    expected_sell_fee_chf: float
    net_pnl_chf: float
    fee_adjusted_pnl_pct: float
    break_even_price_chf: float


@dataclass
class EntrySignal:
    decision: EntryDecision
    reference_price_chf: float | None
    discount_pct: float | None
    reason: str


def calculate_fee_adjusted_pnl(
    position: BuyPosition,
    current_price_chf: float,
    exchange_fee_rate: float,
) -> FeeAdjustedPnL:
    """
    Calculate unrealized PnL with expected exit fees deducted.
    
    For an open BUY position, compute:
    - Gross PnL: what profit would be if we sold now before fees
    - Expected sell fee: what we'd pay in fees to exit
    - Net PnL: gross profit minus exit fees (true profit after closing)
    - Break-even price: price at which net PnL = 0
    """
    cost_basis = (position.quantity_btc * position.unit_price_usd) + position.fee_usd
    current_value = position.quantity_btc * current_price_chf
    
    expected_sell_fee = current_value * exchange_fee_rate
    gross_pnl = current_value - cost_basis
    net_pnl = gross_pnl - expected_sell_fee
    
    fee_adjusted_pnl_pct = (net_pnl / cost_basis) * 100 if cost_basis > 0 else 0
    
    total_fees = position.fee_usd + expected_sell_fee
    break_even_value = cost_basis + total_fees
    break_even_price = break_even_value / position.quantity_btc if position.quantity_btc > 0 else 0
    
    return FeeAdjustedPnL(
        gross_pnl_chf=gross_pnl,
        expected_sell_fee_chf=expected_sell_fee,
        net_pnl_chf=net_pnl,
        fee_adjusted_pnl_pct=fee_adjusted_pnl_pct,
        break_even_price_chf=break_even_price,
    )


def evaluate_entry_signal(
    current_price_chf: float,
    reference_prices_chf: list[float],
    buy_entry_discount_pct: float,
) -> EntrySignal:
    if not reference_prices_chf:
        return EntrySignal(
            decision=EntryDecision.SKIP,
            reference_price_chf=None,
            discount_pct=None,
            reason="No recent reference prices available",
        )

    reference_price = sum(reference_prices_chf) / len(reference_prices_chf)
    if reference_price <= 0:
        return EntrySignal(
            decision=EntryDecision.SKIP,
            reference_price_chf=reference_price,
            discount_pct=None,
            reason="Reference price is invalid",
        )

    discount_pct = ((reference_price - current_price_chf) / reference_price) * 100
    if discount_pct >= buy_entry_discount_pct:
        return EntrySignal(
            decision=EntryDecision.BUY,
            reference_price_chf=reference_price,
            discount_pct=discount_pct,
            reason="Current price is discounted enough versus recent average",
        )

    return EntrySignal(
        decision=EntryDecision.SKIP,
        reference_price_chf=reference_price,
        discount_pct=discount_pct,
        reason="Current price is not discounted enough to justify a new buy",
    )


def evaluate_position(
    position: BuyPosition,
    current_price_chf: float,
    take_profit_pct: float,
    stop_loss_pct: float,
    trend: TrendSignal = TrendSignal.NEUTRAL,
    bearish_cycles: int = 0,
    bearish_exit_min_cycles: int = 2,
    enable_bearish_exit: bool = False,
    exchange_fee_rate: float = 0.004,
) -> PositionDecision:
    """
    Evaluate an open position for sell triggers.
    
    Sell triggers (in priority order):
    1. Take-profit: if change_pct >= take_profit_pct (after fee gate)
    2. Stop-loss: if change_pct <= stop_loss_pct (no fee gate)
    3. Bearish exit: if trend has been BEARISH for bearish_exit_min_cycles and profitable
    
    Otherwise:
    - HOLD if change_pct > 0 (in profit)
    - WATCH if change_pct <= 0 (in loss or break-even)
    """
    change_pct = ((current_price_chf - position.unit_price_usd) / position.unit_price_usd) * 100
    
    # Compute fee-adjusted PnL for gate checks
    pnl_info = calculate_fee_adjusted_pnl(position, current_price_chf, exchange_fee_rate)
    
    # Take-profit (gated on profitability after fees)
    if change_pct >= take_profit_pct and pnl_info.net_pnl_chf > 0:
        return PositionDecision(
            buy_id=position.id,
            decision=Decision.SELL,
            change_pct=change_pct,
        )
    
    # Stop-loss (NOT gated on fees - always sell to protect capital)
    if change_pct <= stop_loss_pct:
        return PositionDecision(
            buy_id=position.id,
            decision=Decision.SELL,
            change_pct=change_pct,
        )
    
    # Bearish exit (gated on profitability after fees)
    if (enable_bearish_exit and trend == TrendSignal.BEARISH and 
        bearish_cycles >= bearish_exit_min_cycles and 
        pnl_info.net_pnl_chf > 0):
        return PositionDecision(
            buy_id=position.id,
            decision=Decision.SELL,
            change_pct=change_pct,
        )
    
    # Otherwise: hold if in profit, watch if in loss
    if change_pct > 0:
        return PositionDecision(
            buy_id=position.id,
            decision=Decision.HOLD,
            change_pct=change_pct,
        )

    return PositionDecision(
        buy_id=position.id,
        decision=Decision.WATCH,
        change_pct=change_pct,
    )


def evaluate_trend(
    hourly_metrics: list[HourlyMetric],
    short_window: int,
    long_window: int,
) -> TrendSignal:
    """
    Evaluate market trend based on moving averages.
    
    Returns:
    - BULLISH when short MA > long MA
    - BEARISH when short MA < long MA
    - NEUTRAL when insufficient data or MAs are equal
    """
    if len(hourly_metrics) < 2:
        return TrendSignal.NEUTRAL
    
    # Normalize callers that provide newest-first or oldest-first metrics.
    ordered_metrics = sorted(hourly_metrics, key=lambda metric: metric.hour_start)

    # Compute moving averages using the most recent available data
    short_count = min(short_window, len(ordered_metrics))
    long_count = min(long_window, len(ordered_metrics))
    
    # Use the LAST N samples (most recent prices) for moving average
    short_ma = sum(m.avg_price_usd for m in ordered_metrics[-short_count:]) / short_count
    long_ma = sum(m.avg_price_usd for m in ordered_metrics[-long_count:]) / long_count
    
    if short_ma > long_ma:
        return TrendSignal.BULLISH
    elif short_ma < long_ma:
        return TrendSignal.BEARISH
    else:
        return TrendSignal.NEUTRAL


def compute_dynamic_stop_loss(
    hourly_metrics: list[HourlyMetric],
    base_stop_loss_pct: float,
    atr_multiplier: float,
) -> float:
    """
    Compute dynamic stop-loss based on recent volatility.
    
    Uses last 24 hourly candles (or all available if fewer).
    Returns the more negative of base_stop_loss_pct or volatility-adjusted value.
    """
    if not hourly_metrics:
        return base_stop_loss_pct
    
    # Use the latest 24 entries or all available, independent of input order.
    ordered_metrics = sorted(hourly_metrics, key=lambda metric: metric.hour_start)
    lookback_count = min(24, len(ordered_metrics))
    recent_metrics = ordered_metrics[-lookback_count:]
    
    # Compute average range pct: (high - low) / avg * 100
    range_pcts = []
    for metric in recent_metrics:
        if metric.avg_price_usd > 0:
            range_pct = ((metric.max_price_usd - metric.min_price_usd) / metric.avg_price_usd) * 100
            range_pcts.append(range_pct)
    
    if not range_pcts:
        return base_stop_loss_pct
    
    avg_range_pct = sum(range_pcts) / len(range_pcts)
    dynamic = -(avg_range_pct * atr_multiplier)
    
    # Return the more negative value (wider stop-loss)
    return min(base_stop_loss_pct, dynamic)


def is_crash_guard_active(
    price_samples: list[PriceSample],
    window_minutes: int,
    lookback_days: int = 90,
) -> bool:
    """
    Determine if crash guard should be active based on recent price decline.
    
    Compares the current price decline over window_minutes against the 95th percentile
    of negative moves from the last lookback_days.
    
    Returns True if current decline exceeds the 95th percentile (indicating a crash).
    """
    if not price_samples or len(price_samples) < 2:
        return False
    
    # Sort samples by timestamp
    sorted_samples = sorted(price_samples, key=lambda s: s.sampled_at)
    latest_time = sorted_samples[-1].sampled_at
    window_start_time = latest_time - __import__("datetime").timedelta(minutes=window_minutes)
    lookback_start_time = latest_time - __import__("datetime").timedelta(days=lookback_days)
    
    # Get current window samples (most recent window_minutes)
    current_window = [
        s for s in sorted_samples
        if s.sampled_at >= window_start_time
    ]
    
    if len(current_window) < 2:
        return False
    
    # Calculate current window price change
    current_first_price = current_window[0].price_usd
    current_last_price = current_window[-1].price_usd
    current_change_pct = ((current_last_price - current_first_price) / current_first_price) * 100 if current_first_price > 0 else 0
    
    # Get all samples in lookback period (excluding current window)
    historical_samples = [
        s for s in sorted_samples
        if lookback_start_time <= s.sampled_at < window_start_time
    ]
    
    if len(historical_samples) < 10:
        return False
    
    # Sample at regular intervals to avoid O(n^2) complexity
    # Take every Nth sample where N is calculated to get roughly window_minutes apart
    sample_interval = max(1, int(window_minutes / 5))  # Assuming 5-minute samples
    historical_changes = []
    
    for i in range(0, len(historical_samples) - sample_interval, sample_interval):
        start_sample = historical_samples[i]
        end_sample = historical_samples[i + sample_interval]
        
        if start_sample.price_usd > 0:
            price_change = ((end_sample.price_usd - start_sample.price_usd) / start_sample.price_usd) * 100
            historical_changes.append(price_change)
    
    # If we don't have enough historical price changes, can't compute percentile reliably
    if len(historical_changes) < 20:
        return False
    
    # Find negative changes and compute the 95th percentile
    negative_changes = sorted([c for c in historical_changes if c < 0])
    if not negative_changes:
        # No crashes in history, current decline triggers guard
        percentile_95 = 0
    else:
        # Compute 95th percentile of negative changes
        try:
            percentile_95 = statistics.quantiles(negative_changes, n=20)[18]
        except:
            percentile_95 = negative_changes[max(0, int(len(negative_changes) * 0.95) - 1)]
    
    # Crash guard is active if current decline is more severe than 95th percentile
    return current_change_pct < percentile_95


def compute_wallet(
    net_deposits: float,
    realized_pnl: float,
    open_positions_cost_basis: float,
    open_positions_current_value: float,
) -> tuple[float, float]:
    """
    Compute free cash and total wallet value.
    
    Returns:
        (free_cash, total_wallet) tuple
        - free_cash: Available cash for new trades (excluding invested capital)
        - total_wallet: Total account value (deposits + realized PnL + unrealized PnL)
    """
    free_cash = net_deposits + realized_pnl - open_positions_cost_basis
    unrealized_pnl = open_positions_current_value - open_positions_cost_basis
    total_wallet = net_deposits + realized_pnl + unrealized_pnl
    
    return free_cash, total_wallet


def find_reinvest_candidate(
    positions: list[BuyPosition],
    current_price: float,
    exchange_fee_rate: float = 0.004,
) -> BuyPosition | None:
    """
    Find the best position to sell for reinvestment.
    
    Returns the position with the highest fee-adjusted PnL % among positions where
    fee_adjusted_pnl > 0 (i.e., profitable after fees).
    
    Returns None if no qualifying position exists.
    """
    if not positions:
        return None
    
    # Filter to profitable positions and compute their PnL metrics
    profitable_candidates = []
    for position in positions:
        pnl_info = calculate_fee_adjusted_pnl(position, current_price, exchange_fee_rate)
        
        # Only consider if net PnL is positive (profitable after fees)
        if pnl_info.net_pnl_chf > 0:
            profitable_candidates.append((position, pnl_info.fee_adjusted_pnl_pct))
    
    if not profitable_candidates:
        return None
    
    # Return the position with highest PnL %
    best_position, _ = max(profitable_candidates, key=lambda x: x[1])
    return best_position
