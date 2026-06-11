import pytest
from fastapi import HTTPException

from src import api


def test_market_price_returns_btc_price(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "fetch_btc_price_usd", lambda: 70250.11)

    response = api.market_price("btc")

    assert response.asset_symbol == "BTC"
    assert response.price_usd == 70250.11


def test_market_price_rejects_other_assets() -> None:
    with pytest.raises(HTTPException) as exc:
        api.market_price("ETH")

    assert exc.value.status_code == 400
    assert "Only BTC is supported" in str(exc.value.detail)
