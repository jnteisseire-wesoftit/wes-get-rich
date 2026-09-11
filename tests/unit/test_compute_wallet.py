"""Tests for compute_wallet function."""
import pytest

from src.strategy import compute_wallet


def test_compute_wallet_free_cash_excludes_invested_capital():
    """Free cash should exclude the cost basis of open positions."""
    net_deposits = 1000.0
    realized_pnl = 50.0
    open_cost_basis = 300.0
    open_current_value = 350.0
    
    free_cash, total_wallet = compute_wallet(
        net_deposits=net_deposits,
        realized_pnl=realized_pnl,
        open_positions_cost_basis=open_cost_basis,
        open_positions_current_value=open_current_value,
    )
    
    # free_cash = 1000 + 50 - 300 = 750
    assert free_cash == 750.0
    # total_wallet = 1000 + 50 + (350 - 300) = 1100
    assert total_wallet == 1100.0


def test_compute_wallet_total_includes_unrealized_gains():
    """Total wallet should include unrealized PnL from open positions."""
    net_deposits = 1000.0
    realized_pnl = 100.0
    open_cost_basis = 500.0
    open_current_value = 600.0  # +100 unrealized gain
    
    free_cash, total_wallet = compute_wallet(
        net_deposits=net_deposits,
        realized_pnl=realized_pnl,
        open_positions_cost_basis=open_cost_basis,
        open_positions_current_value=open_current_value,
    )
    
    # free_cash = 1000 + 100 - 500 = 600
    assert free_cash == 600.0
    # total_wallet = 1000 + 100 + (600 - 500) = 1200
    assert total_wallet == 1200.0


def test_compute_wallet_handles_zero_open_positions():
    """When no open positions, all cash is free."""
    net_deposits = 1000.0
    realized_pnl = 50.0
    open_cost_basis = 0.0
    open_current_value = 0.0
    
    free_cash, total_wallet = compute_wallet(
        net_deposits=net_deposits,
        realized_pnl=realized_pnl,
        open_positions_cost_basis=open_cost_basis,
        open_positions_current_value=open_current_value,
    )
    
    # free_cash = 1000 + 50 - 0 = 1050
    assert free_cash == 1050.0
    # total_wallet = 1000 + 50 + (0 - 0) = 1050
    assert total_wallet == 1050.0


def test_compute_wallet_handles_unrealized_losses():
    """When open positions have unrealized losses."""
    net_deposits = 1000.0
    realized_pnl = 0.0
    open_cost_basis = 500.0
    open_current_value = 400.0  # -100 unrealized loss
    
    free_cash, total_wallet = compute_wallet(
        net_deposits=net_deposits,
        realized_pnl=realized_pnl,
        open_positions_cost_basis=open_cost_basis,
        open_positions_current_value=open_current_value,
    )
    
    # free_cash = 1000 + 0 - 500 = 500
    assert free_cash == 500.0
    # total_wallet = 1000 + 0 + (400 - 500) = 900
    assert total_wallet == 900.0


def test_compute_wallet_handles_negative_realized_pnl():
    """When there are realized losses."""
    net_deposits = 1000.0
    realized_pnl = -100.0  # Losses from previous trades
    open_cost_basis = 200.0
    open_current_value = 250.0
    
    free_cash, total_wallet = compute_wallet(
        net_deposits=net_deposits,
        realized_pnl=realized_pnl,
        open_positions_cost_basis=open_cost_basis,
        open_positions_current_value=open_current_value,
    )
    
    # free_cash = 1000 - 100 - 200 = 700
    assert free_cash == 700.0
    # total_wallet = 1000 - 100 + (250 - 200) = 950
    assert total_wallet == 950.0
