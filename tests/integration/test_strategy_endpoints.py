from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src import api
from src.db import HourlyMetric, PriceSample


def test_strategy_history_db_source(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    dummy_conn,
) -> None:
    now = datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(api, "get_connection", lambda _dsn: dummy_conn)
    monkeypatch.setattr(
        api,
        "list_price_samples",
        lambda *_args, **_kwargs: [
            PriceSample(sampled_at=now, price_usd=68000.5, source="kraken"),
        ],
    )

    response = client.get("/strategy/history?asset_symbol=BTC&hours=24&source=db")

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_symbol"] == "BTC"
    assert payload["source"] == "db"
    assert len(payload["samples"]) == 1
    assert payload["samples"][0]["price_usd"] == 68000.5
    assert dummy_conn.closed is True


def test_strategy_metrics_returns_hourly_aggregates(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    dummy_conn,
) -> None:
    h1 = datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc)
    h2 = datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(api, "get_connection", lambda _dsn: dummy_conn)
    monkeypatch.setattr(
        api,
        "get_hourly_metrics",
        lambda *_args, **_kwargs: [
            HourlyMetric(
                hour_start=h1,
                sample_count=12,
                min_price_usd=67500,
                max_price_usd=68000,
                avg_price_usd=67750,
                last_price_usd=67800,
            ),
            HourlyMetric(
                hour_start=h2,
                sample_count=12,
                min_price_usd=67800,
                max_price_usd=68400,
                avg_price_usd=68120,
                last_price_usd=68300,
            ),
        ],
    )

    response = client.get("/strategy/metrics?asset_symbol=BTC&hours=24")

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_symbol"] == "BTC"
    assert payload["current_price_usd"] == 68300
    assert payload["min_price_usd"] == 67500
    assert payload["max_price_usd"] == 68400
    assert len(payload["hourly"]) == 2
    assert dummy_conn.closed is True
