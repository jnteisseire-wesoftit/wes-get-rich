from fastapi.testclient import TestClient

from src import api


class FakeBinanceService:
    def __init__(self, response: dict):
        self.response = response

    def place_market_order(self, **_kwargs):
        return self.response


def test_binance_order_test_mode(client: TestClient, monkeypatch) -> None:
    fake_response = {}
    monkeypatch.setattr(api, "_build_binance_service", lambda _settings: FakeBinanceService(fake_response))

    payload = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "quote_order_qty": 50,
        "test_order": True,
        "persist_transaction": False,
    }
    response = client.post("/binance/order", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "BTCUSDT"
    assert body["side"] == "BUY"
    assert body["test_order"] is True
    assert body["recorded_transaction_id"] is None


def test_binance_order_persist_rejects_test_mode(client: TestClient, monkeypatch) -> None:
    fake_response = {}
    monkeypatch.setattr(api, "_build_binance_service", lambda _settings: FakeBinanceService(fake_response))

    payload = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "quote_order_qty": 50,
        "test_order": True,
        "persist_transaction": True,
    }
    response = client.post("/binance/order", json=payload)

    assert response.status_code == 400
    assert "Cannot persist a Binance test order" in response.json()["detail"]
