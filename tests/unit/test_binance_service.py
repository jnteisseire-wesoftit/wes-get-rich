import pytest

from src.services.binance.service import BinanceService, BinanceServiceError


def test_place_market_order_requires_quantity_or_quote() -> None:
    service = BinanceService(base_url="https://api.binance.com", credentials=None)

    with pytest.raises(BinanceServiceError) as exc:
        service.place_market_order(
            symbol="BTCUSDT",
            side="BUY",
            quantity=None,
            quote_order_qty=None,
            test_order=True,
        )

    assert "Either quantity or quote_order_qty" in str(exc.value)


def test_get_symbol_price_parses_float(monkeypatch: pytest.MonkeyPatch) -> None:
    service = BinanceService(base_url="https://api.binance.com", credentials=None)

    monkeypatch.setattr(
        service,
        "_request_public",
        lambda _method, _path, _params=None: {"symbol": "BTCUSDT", "price": "70001.12"},
    )

    assert service.get_symbol_price("BTCUSDT") == 70001.12
