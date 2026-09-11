from dataclasses import dataclass
from decimal import Decimal
from unittest.mock import MagicMock

from src import main


@dataclass
class DummyConn:
    closed: bool = False

    def close(self) -> None:
        self.closed = True


def test_run_cycle_skips_buy_when_price_not_discounted(monkeypatch) -> None:
    dummy_conn = DummyConn()
    insert_calls: list[dict] = []

    class FakeSettings:
        dsn = "dsn"
        exchange_fee_rate = 0.001
        asset_symbol = "BTC"
        strategy_tag = "dca-v1"
        wallet_fraction_per_trade = 0.1
        max_open_positions = 10
        min_minutes_between_trades = 1440
        take_profit_pct = 5.0
        stop_loss_pct = -3.0
        dynamic_stop_loss_atr_multiplier = 1.5
        trend_short_window_hours = 6
        trend_long_window_hours = 24
        bearish_exit_min_cycles = 2

    monkeypatch.setattr(main, "Settings", lambda: FakeSettings())
    monkeypatch.setattr(main, "get_connection", lambda _dsn: dummy_conn)
    monkeypatch.setattr(main, "fetch_btc_price_chf", lambda: 100.0)
    monkeypatch.setattr(main, "evaluate_trend", lambda **kwargs: main.TrendSignal.NEUTRAL)
    monkeypatch.setattr(main, "get_hourly_metrics", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main, "get_open_buys", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main, "insert_buy", lambda **kwargs: insert_calls.append(kwargs) or 1)
    monkeypatch.setattr(main, "close_with_sell", lambda *args, **kwargs: 999)

    main.run_cycle()

    assert insert_calls == []
    assert dummy_conn.closed is True


def test_run_cycle_buys_when_price_discounted(monkeypatch) -> None:
    dummy_conn = DummyConn()
    insert_calls: list[dict] = []

    class FakeSettings:
        dsn = "dsn"
        exchange_fee_rate = 0.001
        asset_symbol = "BTC"
        strategy_tag = "dca-v1"
        wallet_fraction_per_trade = 0.1
        max_open_positions = 10
        min_minutes_between_trades = 1440
        take_profit_pct = 5.0
        stop_loss_pct = -3.0
        dynamic_stop_loss_atr_multiplier = 1.5
        trend_short_window_hours = 6
        trend_long_window_hours = 24
        bearish_exit_min_cycles = 2

    monkeypatch.setattr(main, "Settings", lambda: FakeSettings())
    monkeypatch.setattr(main, "get_connection", lambda _dsn: dummy_conn)
    monkeypatch.setattr(main, "fetch_btc_price_chf", lambda: 98.0)
    monkeypatch.setattr(main, "evaluate_trend", lambda **kwargs: main.TrendSignal.BULLISH)
    monkeypatch.setattr(main, "get_hourly_metrics", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main, "get_last_buy_time", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "get_price_samples_window", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main, "is_crash_guard_active", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(main, "get_wallet_summary", lambda *_args, **_kwargs: MagicMock(
        net_deposits=100.0, realized_pnl=0.0, open_cost_basis=0.0
    ))
    monkeypatch.setattr(main, "get_open_buys", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main, "insert_buy", lambda **kwargs: insert_calls.append(kwargs) or 1)
    monkeypatch.setattr(main, "close_with_sell", lambda *args, **kwargs: 999)

    main.run_cycle()

    assert len(insert_calls) == 1
    assert insert_calls[0]["quantity_btc"] > 0
    assert dummy_conn.closed is True
