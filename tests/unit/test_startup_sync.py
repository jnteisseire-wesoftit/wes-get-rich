import asyncio

from src import api


def test_startup_trade_sync_calls_idempotent_import(monkeypatch) -> None:
    calls = []

    def fake_sync(settings) -> dict[str, object]:
        calls.append(settings)
        return {"synced_count": 0, "skipped_count": 1, "errors": []}

    monkeypatch.setattr(api, "_sync_kraken_trades_to_db", fake_sync)
    monkeypatch.setattr(api, "Settings", lambda: object())

    asyncio.run(api._sync_kraken_trades_on_startup())

    assert len(calls) == 1