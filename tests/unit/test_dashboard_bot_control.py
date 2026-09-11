from pathlib import Path


def test_dashboard_contains_bot_control_and_api_wiring() -> None:
    dashboard = Path(__file__).parents[2] / "frontend" / "index.html"
    content = dashboard.read_text(encoding="utf-8")

    assert 'id="bot-toggle"' in content
    assert 'id="bot-state"' in content
    assert "`${API_BASE}/bot/status`" in content
    assert "`${API_BASE}/bot/${running ? 'pause' : 'start'}`" in content