from datetime import datetime

from src.db import BuyPosition, HourlyMetric, PriceSample


def test_quote_currency_aliases_expose_chf_for_strategy_models() -> None:
    buy = BuyPosition(1, 0.1, 100.0, 1.0)
    sample = PriceSample(datetime(2026, 1, 1), 100.0, "test")
    metric = HourlyMetric(datetime(2026, 1, 1), 1, 99.0, 101.0, 100.0, 100.0)

    assert buy.unit_price_chf == 100.0
    assert buy.fee_chf == 1.0
    assert sample.price_chf == 100.0
    assert metric.min_price_chf == 99.0
    assert metric.max_price_chf == 101.0
    assert metric.avg_price_chf == 100.0
    assert metric.last_price_chf == 100.0