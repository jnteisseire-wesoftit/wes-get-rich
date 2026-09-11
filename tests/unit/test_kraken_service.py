import pytest

from src.services.kraken.service import KrakenService


def test_fetch_fee_rate_reads_kraken_trade_volume_fee(monkeypatch: pytest.MonkeyPatch) -> None:
    service = KrakenService(api_key="key", api_secret="secret")
    monkeypatch.setattr(
        service,
        "_request_private",
        lambda path, payload: {"fees": {"XBTCHF": {"fee": "0.8"}}},
    )

    assert service.fetch_fee_rate("XBTCHF") == pytest.approx(0.008)