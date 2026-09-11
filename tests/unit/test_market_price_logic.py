import pytest
from fastapi import HTTPException

from src import api


def test_market_price_returns_btc_price(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeKraken:
        def fetch_spot_price_usd(self, pair: str) -> float:
            return 70250.11

    monkeypatch.setattr(api, "_build_kraken_service", lambda _settings: FakeKraken())

    response = api.market_price("btc")

    assert response.asset_symbol == "BTC"
    assert response.price_chf == 70250.11


def test_market_price_rejects_other_assets() -> None:
    with pytest.raises(HTTPException) as exc:
        api.market_price("ETH")

    assert exc.value.status_code == 400
    assert "Only BTC is supported" in str(exc.value.detail)
