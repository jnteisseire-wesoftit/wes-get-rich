"""Tests for backtest simulation service."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, call

from src.services.backtest.service import run_simulation, SimulationMetrics
from src.services.backtest.service import (
    _build_hourly_metrics,
    _compute_net_trade_pnl,
    _compute_unrealized_pnl,
    _samples_up_to,
)
from src.db import PriceSample


@pytest.fixture
def base_parameters():
    """Base strategy parameters for simulations."""
    return {
        'wallet_fraction_per_trade': 0.10,
        'max_open_positions': 10,
        'min_minutes_between_trades': 1440,
        'take_profit_pct': 5.0,
        'stop_loss_pct': -3.0,
        'dynamic_stop_loss_atr_multiplier': 1.5,
        'trend_short_window_hours': 6,
        'trend_long_window_hours': 24,
        'bearish_exit_min_cycles': 2,
        'exchange_fee_rate': 0.001,
    }


def test_simulation_metrics_dataclass():
    """SimulationMetrics should store all required fields."""
    metrics = SimulationMetrics(
        total_buys=10,
        total_sells=5,
        realized_pnl=500.0,
        unrealized_pnl_at_end=1000.0,
        total_return_pct=15.0,
        win_rate_pct=80.0,
        crash_guard_activations=2,
    )
    
    assert metrics.total_buys == 10
    assert metrics.total_sells == 5
    assert metrics.realized_pnl == 500.0
    assert metrics.unrealized_pnl_at_end == 1000.0
    assert metrics.total_return_pct == 15.0
    assert metrics.win_rate_pct == 80.0
    assert metrics.crash_guard_activations == 2


def test_samples_up_to_uses_sorted_timestamp_index():
    """Historical lookup should return only samples available at the step."""
    samples = [
        PriceSample(datetime(2024, 1, 1, hour), 100.0 + hour, "test")
        for hour in range(3)
    ]

    sample_end, available = _samples_up_to(
        samples,
        [sample.sampled_at for sample in samples],
        datetime(2024, 1, 1, 1, 30),
    )

    assert sample_end == 2
    assert available == samples[:2]


def test_build_hourly_metrics_aggregates_five_minute_samples():
    samples = [
        PriceSample(datetime(2024, 1, 1) + timedelta(minutes=minute), price, "test")
        for minute, price in ((0, 100.0), (5, 102.0), (60, 110.0))
    ]

    metrics = _build_hourly_metrics(samples)

    assert len(metrics) == 2
    assert metrics[0].min_price_usd == 100.0
    assert metrics[0].max_price_usd == 102.0
    assert metrics[0].avg_price_usd == 101.0
    assert metrics[0].last_price_usd == 102.0


def test_compute_unrealized_pnl_uses_final_market_price():
    open_buys = [(0.1, 100.0, 1.0, datetime(2024, 1, 1), 1)]

    assert _compute_unrealized_pnl(open_buys, 120.0) == pytest.approx(1.0)


def test_net_trade_pnl_includes_buy_and_sell_fees():
    assert _compute_net_trade_pnl(1.0, 100.0, 1.0, 100.0, 1.0) == pytest.approx(-2.0)


def test_bearish_exit_requires_configured_cycles(base_parameters):
    from src.services.backtest.service import _should_exit_bearish
    from src.strategy import TrendSignal

    assert not _should_exit_bearish(TrendSignal.BEARISH, 1, 2, 1.0)
    assert _should_exit_bearish(TrendSignal.BEARISH, 2, 2, 1.0, enabled=True)
    assert not _should_exit_bearish(TrendSignal.BEARISH, 2, 2, -1.0)


def test_run_simulation_raises_on_missing_parameters(base_parameters):
    """Should raise ValueError when required parameters are missing."""
    invalid_params = {k: v for k, v in base_parameters.items() if k != 'wallet_fraction_per_trade'}
    
    mock_conn = MagicMock()
    
    with pytest.raises(ValueError, match="Missing required parameter"):
        run_simulation(
            mock_conn,
            "test_sim",
            "BTC",
            datetime.now(),
            datetime.now() + timedelta(days=1),
            10000.0,
            invalid_params,
        )


def test_run_simulation_validates_all_required_parameters(base_parameters):
    """Should validate each required parameter is present."""
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
    
    mock_conn = MagicMock()
    
    for param in required_params:
        invalid_params = {k: v for k, v in base_parameters.items() if k != param}
        with pytest.raises(ValueError, match=f"Missing required parameter: {param}"):
            run_simulation(
                mock_conn,
                "test_sim",
                "BTC",
                datetime.now(),
                datetime.now() + timedelta(days=1),
                10000.0,
                invalid_params,
            )


def test_run_simulation_handles_no_price_data(base_parameters):
    """Should raise ValueError when no price samples found."""
    mock_conn = MagicMock()
    
    # Mock cursor for duplicate check: returns None (no existing sim)
    # fetchone returns: first (None for duplicate check), second ((1,) for insert), third (None for fetchall)
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=None)
    
    # Setup fetchone calls in order
    mock_cursor.fetchone.side_effect = [None, (1,)]  # No existing sim, then insert returns id
    mock_cursor.fetchall.return_value = []  # No price samples
    
    mock_conn.cursor.return_value = mock_cursor
    
    with pytest.raises(ValueError, match="No price samples found"):
        run_simulation(
            mock_conn,
            "no_data_sim",
            "BTC",
            datetime(2024, 1, 1),
            datetime(2024, 1, 2),
            10000.0,
            base_parameters,
        )


def test_run_simulation_replaces_existing_named_run(base_parameters):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=None)
    mock_cursor.fetchone.side_effect = [(42,), (43,)]
    mock_conn.cursor.return_value = mock_cursor

    with pytest.raises(ValueError, match="No price samples found"):
        run_simulation(
            mock_conn,
            "test",
            "BTC",
            datetime(2024, 1, 1),
            datetime(2024, 1, 2),
            10000.0,
            base_parameters,
        )

    mock_cursor.execute.assert_any_call("DELETE FROM simulations WHERE id = %s", (42,))


def test_run_simulation_simulations_table_structure():
    """Test that the simulation properly initializes simulation record."""
    # This is more of a documentation test showing expected behavior
    # In real usage, run_simulation would persist to DB
    
    metrics = SimulationMetrics(
        total_buys=5,
        total_sells=3,
        realized_pnl=200.0,
        unrealized_pnl_at_end=500.0,
        total_return_pct=7.0,
        win_rate_pct=66.7,
        crash_guard_activations=0,
    )
    
    # Verify structure matches what's expected in simulation_metrics table
    assert hasattr(metrics, 'total_buys')
    assert hasattr(metrics, 'total_sells')
    assert hasattr(metrics, 'realized_pnl')
    assert hasattr(metrics, 'unrealized_pnl_at_end')
    assert hasattr(metrics, 'total_return_pct')
    assert hasattr(metrics, 'win_rate_pct')
    assert hasattr(metrics, 'crash_guard_activations')

