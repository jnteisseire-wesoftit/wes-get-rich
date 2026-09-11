from src.db import BuyPosition
from src.strategy import (
    Decision,
    EntryDecision,
    TrendSignal,
    evaluate_entry_signal,
    evaluate_position,
)


def test_evaluate_entry_signal_buys_on_sufficient_discount() -> None:
    signal = evaluate_entry_signal(
        current_price_chf=98.0,
        reference_prices_chf=[100.0, 100.0, 100.0],
        buy_entry_discount_pct=1.0,
    )

    assert signal.decision == EntryDecision.BUY
    assert signal.discount_pct == 2.0
    assert signal.reference_price_chf == 100.0


def test_evaluate_entry_signal_skips_when_discount_too_small() -> None:
    signal = evaluate_entry_signal(
        current_price_chf=99.5,
        reference_prices_chf=[100.0, 100.0, 100.0],
        buy_entry_discount_pct=1.0,
    )

    assert signal.decision == EntryDecision.SKIP
    assert signal.discount_pct == 0.5
    assert signal.reference_price_chf == 100.0


def test_evaluate_position_sells_on_bearish_exit_after_min_cycles():
    """Should sell when bearish for min_cycles and position is profitable."""
    position = BuyPosition(id=1, quantity_btc=1.0, unit_price_usd=100.0, fee_usd=1.0)
    current_price = 110.0  # +10%, profitable
    
    decision = evaluate_position(
        position=position,
        current_price_chf=current_price,
        take_profit_pct=15.0,  # Not triggered
        stop_loss_pct=-3.0,    # Not triggered
        trend=TrendSignal.BEARISH,
        bearish_cycles=2,      # At threshold
        bearish_exit_min_cycles=2,
        enable_bearish_exit=True,
        exchange_fee_rate=0.001,
    )
    
    assert decision.decision == Decision.SELL


def test_evaluate_position_holds_when_bearish_cycles_below_threshold():
    """Should hold even if bearish when cycles below threshold."""
    position = BuyPosition(id=1, quantity_btc=1.0, unit_price_usd=100.0, fee_usd=1.0)
    current_price = 110.0  # +10%, profitable
    
    decision = evaluate_position(
        position=position,
        current_price_chf=current_price,
        take_profit_pct=15.0,
        stop_loss_pct=-3.0,
        trend=TrendSignal.BEARISH,
        bearish_cycles=1,      # Below threshold
        bearish_exit_min_cycles=2,
        exchange_fee_rate=0.001,
    )
    
    assert decision.decision == Decision.HOLD


def test_evaluate_position_holds_bearish_profit_by_default():
    position = BuyPosition(id=1, quantity_btc=1.0, unit_price_usd=100.0, fee_usd=1.0)

    decision = evaluate_position(
        position=position,
        current_price_chf=110.0,
        take_profit_pct=15.0,
        stop_loss_pct=-3.0,
        trend=TrendSignal.BEARISH,
        bearish_cycles=10,
        bearish_exit_min_cycles=2,
        exchange_fee_rate=0.001,
    )

    assert decision.decision == Decision.HOLD


def test_evaluate_position_stop_loss_ignores_fee_gate():
    """Stop-loss should trigger regardless of profitability after fees."""
    position = BuyPosition(id=1, quantity_btc=1.0, unit_price_usd=100.0, fee_usd=1.0)
    current_price = 97.0  # -3%, at stop-loss
    
    decision = evaluate_position(
        position=position,
        current_price_chf=current_price,
        take_profit_pct=5.0,
        stop_loss_pct=-3.0,
        trend=TrendSignal.BULLISH,
        bearish_cycles=0,
        bearish_exit_min_cycles=2,
        exchange_fee_rate=0.10,  # Very high fees
    )
    
    # Should sell despite high fees
    assert decision.decision == Decision.SELL


def test_evaluate_position_bearish_exit_requires_profitability():
    """Bearish exit should not trigger if position is unprofitable after fees."""
    position = BuyPosition(id=1, quantity_btc=1.0, unit_price_usd=100.0, fee_usd=1.0)
    current_price = 100.5  # Very small gain, won't cover fees
    
    decision = evaluate_position(
        position=position,
        current_price_chf=current_price,
        take_profit_pct=5.0,
        stop_loss_pct=-3.0,
        trend=TrendSignal.BEARISH,
        bearish_cycles=2,
        bearish_exit_min_cycles=2,
        enable_bearish_exit=True,
        exchange_fee_rate=0.01,  # 1% exit fee
    )
    
    # Should hold because net PnL is negative
    assert decision.decision == Decision.HOLD
