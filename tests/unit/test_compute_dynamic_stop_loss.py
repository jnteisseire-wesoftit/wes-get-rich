"""Tests for compute_dynamic_stop_loss function."""
import pytest
from datetime import datetime

from src.strategy import compute_dynamic_stop_loss
from tests.unit.test_datasets import HourlyMetricDatasets


def test_compute_dynamic_stop_loss_widens_during_high_volatility():
    """When volatility is high, stop-loss widens (becomes more negative)."""
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    metrics = HourlyMetricDatasets.get_high_volatility_metrics(
        base_time=base_time,
        hours=24,
    )
    
    base_stop_loss = -3.0
    atr_multiplier = 1.5
    
    result = compute_dynamic_stop_loss(
        hourly_metrics=metrics,
        base_stop_loss_pct=base_stop_loss,
        atr_multiplier=atr_multiplier,
    )
    
    # With high volatility, result should be more negative (wider) than base
    assert result < base_stop_loss


def test_compute_dynamic_stop_loss_uses_base_when_volatility_is_low():
    """When volatility is low, use base stop-loss."""
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    metrics = HourlyMetricDatasets.get_low_volatility_metrics(
        base_time=base_time,
        hours=24,
    )
    
    base_stop_loss = -3.0
    atr_multiplier = 1.5
    
    result = compute_dynamic_stop_loss(
        hourly_metrics=metrics,
        base_stop_loss_pct=base_stop_loss,
        atr_multiplier=atr_multiplier,
    )
    
    # With low volatility, result should be base stop-loss or close to it
    assert result >= base_stop_loss


def test_compute_dynamic_stop_loss_returns_base_when_no_data():
    """When no hourly metrics, return base stop-loss."""
    base_stop_loss = -3.0
    atr_multiplier = 1.5
    
    result = compute_dynamic_stop_loss(
        hourly_metrics=[],
        base_stop_loss_pct=base_stop_loss,
        atr_multiplier=atr_multiplier,
    )
    
    assert result == base_stop_loss


def test_compute_dynamic_stop_loss_uses_last_24_entries():
    """Only use last 24 entries regardless of data size."""
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    
    # Get 50 hours of metrics, but only last 24 should be used
    metrics = HourlyMetricDatasets.get_high_volatility_metrics(
        base_time=base_time,
        hours=50,
    )
    
    base_stop_loss = -3.0
    atr_multiplier = 1.5
    
    result = compute_dynamic_stop_loss(
        hourly_metrics=metrics,
        base_stop_loss_pct=base_stop_loss,
        atr_multiplier=atr_multiplier,
    )
    
    # Result should be a valid number
    assert isinstance(result, float)
    assert result <= base_stop_loss  # Always more negative or equal
