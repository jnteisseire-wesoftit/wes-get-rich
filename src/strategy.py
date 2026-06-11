from dataclasses import dataclass
from enum import Enum

from .db import BuyPosition


class Decision(str, Enum):
    SELL = "SELL"
    HOLD = "HOLD"
    WATCH = "WATCH"


@dataclass
class PositionDecision:
    buy_id: int
    decision: Decision
    change_pct: float


@dataclass
class FeeAdjustedPnL:
    gross_pnl_usd: float
    expected_sell_fee_usd: float
    net_pnl_usd: float
    fee_adjusted_pnl_pct: float
    break_even_price_usd: float


def calculate_fee_adjusted_pnl(
    position: BuyPosition,
    current_price_usd: float,
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
    current_value = position.quantity_btc * current_price_usd
    
    expected_sell_fee = current_value * exchange_fee_rate
    gross_pnl = current_value - cost_basis
    net_pnl = gross_pnl - expected_sell_fee
    
    fee_adjusted_pnl_pct = (net_pnl / cost_basis) * 100 if cost_basis > 0 else 0
    
    total_fees = position.fee_usd + expected_sell_fee
    break_even_value = cost_basis + total_fees
    break_even_price = break_even_value / position.quantity_btc if position.quantity_btc > 0 else 0
    
    return FeeAdjustedPnL(
        gross_pnl_usd=gross_pnl,
        expected_sell_fee_usd=expected_sell_fee,
        net_pnl_usd=net_pnl,
        fee_adjusted_pnl_pct=fee_adjusted_pnl_pct,
        break_even_price_usd=break_even_price,
    )


def evaluate_position(
    position: BuyPosition,
    current_price_usd: float,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> PositionDecision:
    change_pct = ((current_price_usd - position.unit_price_usd) / position.unit_price_usd) * 100

    if change_pct >= take_profit_pct:
        return PositionDecision(
            buy_id=position.id,
            decision=Decision.SELL,
            change_pct=change_pct,
        )

    if change_pct <= stop_loss_pct:
        return PositionDecision(
            buy_id=position.id,
            decision=Decision.SELL,
            change_pct=change_pct,
        )

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
