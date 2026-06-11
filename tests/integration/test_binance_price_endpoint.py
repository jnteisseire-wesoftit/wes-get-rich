from fastapi.testclient import TestClient

from src import api


class FakeBinanceService:
    def get_symbol_price(self, symbol: str) -> float:
        assert symbol == "BTCUSDT"
        return 70123.45


def test_binance_price_endpoint(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(api, "_build_binance_service", lambda _settings: FakeBinanceService())

    response = client.get("/binance/price?symbol=BTCUSDT")
    assert response.status_code == 200
    assert response.json() == {"symbol": "BTCUSDT", "price": 70123.45}
