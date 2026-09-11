"""Tests for evaluate_trend function."""
import pytest

from src.strategy import TrendSignal, evaluate_trend
from tests.unit.test_datasets import HourlyMetricDatasets
from datetime import datetime


def test_evaluate_trend_bullish_when_short_ma_above_long_ma():
    """When short MA > long MA, trend should be BULLISH."""
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    metrics = HourlyMetricDatasets.get_bullish_metrics(
        base_time=base_time,
        hours=30,
    )
    
    trend = evaluate_trend(
        hourly_metrics=metrics,
        short_window=6,
        long_window=24,
    )
    assert trend == TrendSignal.BULLISH


def test_evaluate_trend_bearish_when_short_ma_below_long_ma():
    """When short MA < long MA, trend should be BEARISH."""
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    metrics = HourlyMetricDatasets.get_bearish_metrics(
        base_time=base_time,
        hours=30,
    )
    
    trend = evaluate_trend(
        hourly_metrics=metrics,
        short_window=6,
        long_window=24,
    )
    assert trend == TrendSignal.BEARISH


def test_evaluate_trend_neutral_when_insufficient_data():
    """When fewer than 2 entries, trend should be NEUTRAL."""
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    metrics = HourlyMetricDatasets.get_stable_metrics(
        base_time=base_time,
        hours=1,
    )
    
    trend = evaluate_trend(
        hourly_metrics=metrics,
        short_window=6,
        long_window=24,
    )
    assert trend == TrendSignal.NEUTRAL


def test_evaluate_trend_neutral_when_mas_are_equal():
    """When short MA == long MA, trend should be NEUTRAL."""
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    metrics = HourlyMetricDatasets.get_stable_metrics(
        base_time=base_time,
        hours=30,
        price=100.0,
    )
    
    trend = evaluate_trend(
        hourly_metrics=metrics,
        short_window=6,
        long_window=24,
    )
    assert trend == TrendSignal.NEUTRAL


def test_evaluate_trend_uses_min_of_window_and_length():
    """When data < window, use available data."""
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    metrics = HourlyMetricDatasets.get_stable_metrics(
        base_time=base_time,
        hours=3,  # Only 3 data points
        price=100.0,
    )
    
    # Request 6-hour and 24-hour windows but only 3 entries exist
    trend = evaluate_trend(
        hourly_metrics=metrics,
        short_window=6,
        long_window=24,
    )
    # Short MA should be mean of 3, long MA should be mean of 3, both equal → NEUTRAL
    assert trend == TrendSignal.NEUTRAL
