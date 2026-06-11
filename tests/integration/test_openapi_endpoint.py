from fastapi.testclient import TestClient


def test_openapi_spec_exposed(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    payload = response.json()
    assert "/health" in payload["paths"]
    assert "/transactions" in payload["paths"]
    assert "/market/price" in payload["paths"]
