from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from src import api


def test_list_transactions_endpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    dummy_conn,
) -> None:
    now = datetime(2026, 6, 10, 10, 15, tzinfo=timezone.utc)

    rows = [
        {
            "id": 1,
            "platform_name": "kraken",
            "asset_symbol": "BTC",
            "action": "BUY",
            "quantity_btc": Decimal("0.0025"),
            "unit_price_usd": Decimal("67000.00"),
            "fee_usd": Decimal("1.50"),
            "paired_buy_transaction_id": None,
            "realized_pnl_usd": None,
            "status": "OPEN",
            "transaction_at": now,
            "strategy_tag": "test",
            "notes": "sample",
            "executed_at": now,
            "created_at": now,
        }
    ]

    monkeypatch.setattr(api, "get_connection", lambda _dsn: dummy_conn)
    monkeypatch.setattr(api, "list_transactions", lambda *_args, **_kwargs: rows)

    response = client.get("/transactions?limit=50")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["asset_symbol"] == "BTC"
    assert body[0]["quantity_btc"] == 0.0025
    assert body[0]["unit_price_usd"] == 67000.0
    assert body[0]["fee_usd"] == 1.5
    assert dummy_conn.closed is True
