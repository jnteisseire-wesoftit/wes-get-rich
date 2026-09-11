from dataclasses import dataclass
from decimal import Decimal

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
        buy_budget_usd = 50.0
        exchange_fee_rate = 0.001
        asset_symbol = "BTC"
        strategy_tag = "dca-v1"
        take_profit_pct = 5.0
        stop_loss_pct = -3.0
        strategy_metrics_window_hours = 24
        buy_entry_discount_pct = 1.0

    monkeypatch.setattr(main, "Settings", lambda: FakeSettings())
    monkeypatch.setattr(main, "get_connection", lambda _dsn: dummy_conn)
    monkeypatch.setattr(main, "fetch_btc_price_usd", lambda: 100.0)
    monkeypatch.setattr(
        main,
        "get_hourly_metrics",
        lambda *_args, **_kwargs: [
            type("Metric", (), {"avg_price_usd": 100.0})(),
            type("Metric", (), {"avg_price_usd": 100.0})(),
        ],
    )
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
        buy_budget_usd = 50.0
        exchange_fee_rate = 0.001
        asset_symbol = "BTC"
        strategy_tag = "dca-v1"
        take_profit_pct = 5.0
        stop_loss_pct = -3.0
        strategy_metrics_window_hours = 24
        buy_entry_discount_pct = 1.0

    monkeypatch.setattr(main, "Settings", lambda: FakeSettings())
    monkeypatch.setattr(main, "get_connection", lambda _dsn: dummy_conn)
    monkeypatch.setattr(main, "fetch_btc_price_usd", lambda: 98.0)
    monkeypatch.setattr(
        main,
        "get_hourly_metrics",
        lambda *_args, **_kwargs: [
            type("Metric", (), {"avg_price_usd": 100.0})(),
            type("Metric", (), {"avg_price_usd": 100.0})(),
        ],
    )
    monkeypatch.setattr(main, "get_open_buys", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main, "insert_buy", lambda **kwargs: insert_calls.append(kwargs) or 1)
    monkeypatch.setattr(main, "close_with_sell", lambda *args, **kwargs: 999)

    main.run_cycle()

    assert len(insert_calls) == 1
    assert insert_calls[0]["quantity_btc"] > 0
    assert dummy_conn.closed is True
