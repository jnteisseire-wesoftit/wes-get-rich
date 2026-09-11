import time
import requests

_cache: dict[str, float] = {}
_CACHE_TTL_SECONDS = 60


def fetch_btc_price_chf() -> float:
    now = time.monotonic()
    cached_price = _cache.get("price")
    cached_at = _cache.get("cached_at", 0.0)

    if cached_price is not None and (now - cached_at) < _CACHE_TTL_SECONDS:
        return cached_price

    response = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": "bitcoin", "vs_currencies": "chf"},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    price = float(payload["bitcoin"]["chf"])

    _cache["price"] = price
    _cache["cached_at"] = now

    return price
