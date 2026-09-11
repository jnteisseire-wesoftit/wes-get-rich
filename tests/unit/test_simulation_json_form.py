from pathlib import Path


def test_simulation_form_uses_json_parameters() -> None:
    page = Path(__file__).parents[2] / "frontend" / "simulations.html"
    content = page.read_text(encoding="utf-8")

    assert 'id="parameters-json"' in content
    assert "JSON.parse(document.getElementById('parameters-json').value)" in content
    assert "Invalid parameters JSON" in content
    assert "wallet_fraction_per_trade" in content
    assert "exchange_fee_rate" not in content
