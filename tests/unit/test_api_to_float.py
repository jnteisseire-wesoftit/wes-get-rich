from decimal import Decimal

from src import api


def test_to_float_returns_none_for_none() -> None:
    assert api._to_float(None) is None


def test_to_float_converts_decimal() -> None:
    assert api._to_float(Decimal("123.45")) == 123.45
