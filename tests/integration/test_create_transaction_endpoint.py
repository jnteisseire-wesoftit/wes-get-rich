import pytest
from fastapi.testclient import TestClient

from src import api


def test_create_transaction_endpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    dummy_conn,
) -> None:

    monkeypatch.setattr(api, "get_connection", lambda _dsn: dummy_conn)
    monkeypatch.setattr(api, "create_transaction", lambda *_args, **_kwargs: 77)

    payload = {
        "platform_name": "kraken",
        "asset_symbol": "btc",
        "action": "BUY",
        "quantity_btc": 0.001,
        "unit_price_usd": 68000,
        "fee_usd": 1.0,
        "status": "OPEN",
        "transaction_at": "2026-06-10T10:00:00Z",
        "strategy_tag": "test",
        "notes": "integration",
    }
    response = client.post("/transactions", json=payload)

    assert response.status_code == 201
    assert response.json() == {"id": 77}
    assert dummy_conn.closed is True
