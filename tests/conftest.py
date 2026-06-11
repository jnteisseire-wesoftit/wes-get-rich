import os

import pytest
from fastapi.testclient import TestClient

from src import api


class DummyConn:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def client() -> TestClient:
    os.environ["ENABLE_PRICE_SAMPLER"] = "false"
    return TestClient(api.app)


@pytest.fixture
def dummy_conn() -> DummyConn:
    return DummyConn()
