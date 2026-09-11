"""Tests for database query functions."""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from src.db import get_last_buy_time, WalletSummary, get_wallet_summary, get_price_samples_window, PriceSample


def test_wallet_summary_dataclass_has_required_fields():
    """WalletSummary should have net_deposits, realized_pnl, and open_cost_basis."""
    summary = WalletSummary(
        net_deposits=1000.0,
        realized_pnl=100.0,
        open_cost_basis=500.0,
    )
    
    assert summary.net_deposits == 1000.0
    assert summary.realized_pnl == 100.0
    assert summary.open_cost_basis == 500.0


def test_get_last_buy_time_returns_most_recent_buy():
    """Should return the transaction_at of the most recent BUY."""
    recent_time = datetime(2024, 1, 15, 10, 0, 0)
    
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=None)
    mock_cursor.fetchone.return_value = (recent_time,)
    mock_conn.cursor.return_value = mock_cursor
    
    result = get_last_buy_time(mock_conn, "BTC")
    
    assert result == recent_time
    mock_cursor.execute.assert_called_once()


def test_get_last_buy_time_returns_none_when_no_buys():
    """Should return None when no BUY transactions exist."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=None)
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value = mock_cursor
    
    result = get_last_buy_time(mock_conn, "BTC")
    
    assert result is None


def test_get_wallet_summary_returns_wallet_summary():
    """Should return WalletSummary with correct values."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=None)
    
    # Mock the row response with dict-like behavior
    mock_row = {
        "net_deposits": 700.0,
        "realized_pnl": 50.0,
        "open_cost_basis": 300.0,
    }
    mock_cursor.fetchone.return_value = mock_row
    mock_conn.cursor.return_value = mock_cursor
    
    summary = get_wallet_summary(mock_conn, "BTC")
    
    assert summary.net_deposits == 700.0
    assert summary.realized_pnl == 50.0
    assert summary.open_cost_basis == 300.0


def test_get_wallet_summary_handles_none():
    """Should handle None result gracefully."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=None)
    mock_cursor.fetchone.return_value = None
    mock_conn.cursor.return_value = mock_cursor
    
    summary = get_wallet_summary(mock_conn, "BTC")
    
    assert summary.net_deposits == 0.0
    assert summary.realized_pnl == 0.0
    assert summary.open_cost_basis == 0.0


def test_get_price_samples_window_returns_price_samples():
    """Should return list of PriceSample objects."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=None)
    
    now = datetime(2024, 1, 15, 10, 0, 0)
    mock_rows = [
        {
            "asset_symbol": "BTC",
            "source": "binance",
            "price_usd": 50000.0,
            "sampled_at": now,
        },
        {
            "asset_symbol": "BTC",
            "source": "binance",
            "price_usd": 50100.0,
            "sampled_at": now,
        },
    ]
    mock_cursor.fetchall.return_value = mock_rows
    mock_conn.cursor.return_value = mock_cursor
    
    result = get_price_samples_window(mock_conn, "BTC", lookback_days=90)
    
    assert len(result) == 2
    assert all(isinstance(s, PriceSample) for s in result)
    assert result[0].price_usd == 50000.0
    assert result[1].price_usd == 50100.0


def test_get_price_samples_window_returns_empty_list():
    """Should return empty list when no samples exist."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=None)
    mock_cursor.fetchall.return_value = []
    mock_conn.cursor.return_value = mock_cursor
    
    result = get_price_samples_window(mock_conn, "BTC", lookback_days=90)
    
    assert result == []
