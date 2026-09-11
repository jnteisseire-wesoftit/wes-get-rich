from fastapi.testclient import TestClient

from src import api


class FakeKrakenService:
    def __init__(self, pair: str = "XBTCHF"):
        self.pair = pair
        self.requests = []

    def fetch_spot_price_usd(self, pair: str = "XBTUSD") -> float:
        assert pair == self.pair
        return 62500.0

    def place_market_order(self, **kwargs):
        self.requests.append(kwargs)
        return {"descr": {"order": "buy 0.00016000 XBTUSD @ market"}, "txid": ["ABC123"]}


def test_kraken_order_validate_only(client: TestClient, monkeypatch) -> None:
    class FakeSettings:
        live_trading_enabled = True
        kraken_trading_pair = "XBTCHF"

    service = FakeKrakenService(pair="XBTCHF")
    monkeypatch.setattr(api, "Settings", lambda: FakeSettings())
    monkeypatch.setattr(api, "_build_kraken_service", lambda _settings: service)

    response = client.post(
        "/kraken/order",
        json={
            "side": "BUY",
            "quote_order_qty": 10,
            "validate_only": True,
            "persist_transaction": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["validate_only"] is True
    assert payload["pair"] == "XBTCHF"
    assert payload["txid"] == ["ABC123"]
    assert service.requests[0]["validate_only"] is True


def test_kraken_order_rejects_live_when_disabled(client: TestClient, monkeypatch) -> None:
    class FakeSettings:
        live_trading_enabled = False
        kraken_trading_pair = "XBTCHF"

    service = FakeKrakenService(pair="XBTCHF")
    monkeypatch.setattr(api, "Settings", lambda: FakeSettings())
    monkeypatch.setattr(api, "_build_kraken_service", lambda _settings: service)

    response = client.post(
        "/kraken/order",
        json={
            "side": "BUY",
            "quote_order_qty": 10,
            "validate_only": False,
            "persist_transaction": False,
        },
    )

    assert response.status_code == 403
    assert "LIVE_TRADING_ENABLED" in response.json()["detail"]