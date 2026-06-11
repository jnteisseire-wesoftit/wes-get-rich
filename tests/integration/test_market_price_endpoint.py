import pytest
from fastapi.testclient import TestClient

from src import api


def test_market_price_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "fetch_btc_price_usd", lambda: 69999.9)

    response = client.get("/market/price?asset_symbol=BTC")

    assert response.status_code == 200
    assert response.json() == {"asset_symbol": "BTC", "price_usd": 69999.9}


def test_market_price_rejects_non_btc(client: TestClient) -> None:
    response = client.get("/market/price?asset_symbol=ETH")
    assert response.status_code == 400
    assert response.json()["detail"] == "Only BTC is supported for now"
