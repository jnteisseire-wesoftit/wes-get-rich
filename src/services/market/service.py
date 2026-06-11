import requests


def fetch_btc_price_usd() -> float:
    response = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": "bitcoin", "vs_currencies": "usd"},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    return float(payload["bitcoin"]["usd"])
