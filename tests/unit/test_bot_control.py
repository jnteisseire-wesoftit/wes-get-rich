import asyncio

from fastapi.testclient import TestClient

from src import api


def test_bot_starts_paused() -> None:
    api.app.state.bot_task = None

    response = api.bot_status()

    assert response.running is False


def test_bot_start_and_pause_control_task(monkeypatch) -> None:
    async def idle_loop() -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(api, "_bot_loop", idle_loop)
    api.app.state.bot_task = None

    async def exercise_controls() -> None:
        started = await api.start_bot()
        assert started.running is True
        assert api.bot_status().running is True

        paused = await api.pause_bot()
        assert paused.running is False

    asyncio.run(exercise_controls())
    assert api.app.state.bot_task is None


def test_start_bot_is_idempotent(monkeypatch) -> None:
    async def idle_loop() -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(api, "_bot_loop", idle_loop)

    async def exercise_controls() -> None:
        first = await api.start_bot()
        first_task = api.app.state.bot_task
        second = await api.start_bot()

        assert first.running is True
        assert second.running is True
        assert api.app.state.bot_task is first_task

        await api.pause_bot()

    asyncio.run(exercise_controls())


def test_bot_control_http_endpoints(monkeypatch) -> None:
    class FakeSettings:
        kraken_api_key = ""
        kraken_api_secret = ""
        enable_price_sampler = False

    async def idle_loop() -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(api, "Settings", lambda: FakeSettings())
    monkeypatch.setattr(api, "_bot_loop", idle_loop)

    with TestClient(api.app) as client:
        assert client.get("/bot/status").json() == {"running": False}
        assert client.post("/bot/start").json() == {"running": True}
        assert client.get("/bot/status").json() == {"running": True}
        assert client.post("/bot/pause").json() == {"running": False}