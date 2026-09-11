from fastapi.testclient import TestClient

from src import api


class FakeKrakenService:
    def fetch_balances(self) -> dict[str, float]:
        return {"ZEUR": 208.64, "XXBT": 0.0012}


class FailingKrakenService:
    def fetch_balances(self) -> dict[str, float]:
        raise api.KrakenServiceError("Kraken API credentials are required")


def test_kraken_balance_endpoint_success(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(api, "_build_kraken_service", lambda _settings: FakeKrakenService())

    response = client.get("/kraken/balance")

    assert response.status_code == 200
    payload = response.json()
    assert payload["live_trading_enabled"] is False
    assert payload["balances"]["ZEUR"] == 208.64
    assert payload["balances"]["XXBT"] == 0.0012


def test_kraken_balance_endpoint_handles_service_error(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(api, "_build_kraken_service", lambda _settings: FailingKrakenService())

    response = client.get("/kraken/balance")

    assert response.status_code == 400
    assert "credentials" in response.json()["detail"].lower()
