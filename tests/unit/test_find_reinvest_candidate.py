"""Tests for find_reinvest_candidate function."""
import pytest

from src.db import BuyPosition
from src.strategy import find_reinvest_candidate, calculate_fee_adjusted_pnl


def test_find_reinvest_candidate_returns_most_profitable():
    """Should return position with highest fee-adjusted PnL %."""
    positions = [
        BuyPosition(id=1, quantity_btc=1.0, unit_price_usd=100.0, fee_usd=1.0),
        BuyPosition(id=2, quantity_btc=1.0, unit_price_usd=100.0, fee_usd=1.0),
        BuyPosition(id=3, quantity_btc=1.0, unit_price_usd=100.0, fee_usd=1.0),
    ]
    
    current_price = 110.0
    exchange_fee_rate = 0.001
    
    # Position 1: pnl_pct = (110*1 - 101) / 101 * 100 = 8.9%
    # Position 2: pnl_pct = same, 8.9%
    # Position 3: pnl_pct = same, 8.9%
    # Should return any of them (first one found)
    candidate = find_reinvest_candidate(
        positions=positions,
        current_price=current_price,
        exchange_fee_rate=exchange_fee_rate,
    )
    
    assert candidate is not None
    assert candidate.id in [1, 2, 3]


def test_find_reinvest_candidate_returns_none_when_all_at_loss():
    """Should return None when all positions are unprofitable."""
    positions = [
        BuyPosition(id=1, quantity_btc=1.0, unit_price_usd=100.0, fee_usd=1.0),
        BuyPosition(id=2, quantity_btc=1.0, unit_price_usd=100.0, fee_usd=1.0),
    ]
    
    current_price = 99.0  # Below cost basis
    exchange_fee_rate = 0.001
    
    candidate = find_reinvest_candidate(
        positions=positions,
        current_price=current_price,
        exchange_fee_rate=exchange_fee_rate,
    )
    
    assert candidate is None


def test_find_reinvest_candidate_returns_none_when_no_positions():
    """Should return None when position list is empty."""
    candidate = find_reinvest_candidate(
        positions=[],
        current_price=110.0,
        exchange_fee_rate=0.001,
    )
    
    assert candidate is None


def test_find_reinvest_candidate_excludes_positions_where_fee_exceeds_profit():
    """Should exclude positions where fees wipe out profits."""
    positions = [
        BuyPosition(id=1, quantity_btc=1.0, unit_price_usd=100.0, fee_usd=1.0),
        BuyPosition(id=2, quantity_btc=1.0, unit_price_usd=100.0, fee_usd=1.0),
    ]
    
    current_price = 101.0  # Only 1% gain
    exchange_fee_rate = 0.02  # 2% exit fee on current value
    
    # Position 1: gross gain = 1%, exit fee = 2.02%, net = -1.02%
    # Position 2: same
    # Both should fail fee gate
    candidate = find_reinvest_candidate(
        positions=positions,
        current_price=current_price,
        exchange_fee_rate=exchange_fee_rate,
    )
    
    assert candidate is None


def test_find_reinvest_candidate_picks_highest_profit_when_multiple_qualify():
    """Should pick the position with highest fee-adjusted PnL % among profitable ones."""
    positions = [
        BuyPosition(id=1, quantity_btc=1.0, unit_price_usd=100.0, fee_usd=1.0),  # ~8% PnL
        BuyPosition(id=2, quantity_btc=1.0, unit_price_usd=100.0, fee_usd=1.0),  # ~8% PnL
        BuyPosition(id=3, quantity_btc=1.0, unit_price_usd=90.0, fee_usd=1.0),   # ~22% PnL (lowest cost basis)
    ]
    
    current_price = 110.0
    exchange_fee_rate = 0.001
    
    candidate = find_reinvest_candidate(
        positions=positions,
        current_price=current_price,
        exchange_fee_rate=exchange_fee_rate,
    )
    
    # Position 3 should be selected as it has highest PnL %
    assert candidate is not None
    assert candidate.id == 3


def test_find_reinvest_candidate_mixed_profitable_and_loss():
    """Should only return profitable positions, skip loss-making ones."""
    positions = [
        BuyPosition(id=1, quantity_btc=1.0, unit_price_usd=100.0, fee_usd=1.0),  # Profitable
        BuyPosition(id=2, quantity_btc=1.0, unit_price_usd=110.0, fee_usd=1.0),  # At loss
        BuyPosition(id=3, quantity_btc=1.0, unit_price_usd=105.0, fee_usd=1.0),  # Profitable
    ]
    
    current_price = 110.0
    exchange_fee_rate = 0.001
    
    candidate = find_reinvest_candidate(
        positions=positions,
        current_price=current_price,
        exchange_fee_rate=exchange_fee_rate,
    )
    
    # Should return either position 1 or 3 (both profitable)
    assert candidate is not None
    assert candidate.id in [1, 3]
