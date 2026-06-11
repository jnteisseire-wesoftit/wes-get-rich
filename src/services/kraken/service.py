from dataclasses import dataclass
from datetime import datetime, timezone

import requests


@dataclass
class KrakenOhlcSample:
    sampled_at: datetime
    price_usd: float


class KrakenServiceError(RuntimeError):
    pass


class KrakenService:
    def __init__(self, base_url: str = "https://api.kraken.com") -> None:
        self.base_url = base_url.rstrip("/")

    def fetch_spot_price_usd(self, pair: str = "XBTUSD") -> float:
        response = requests.get(
            f"{self.base_url}/0/public/Ticker",
            params={"pair": pair},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()

        if payload.get("error"):
            raise KrakenServiceError(f"Kraken ticker error: {payload['error']}")

        result = payload.get("result") or {}
        if not result:
            raise KrakenServiceError("Kraken ticker result is empty")

        pair_data = next(iter(result.values()))
        close = pair_data.get("c")
        if not close or not close[0]:
            raise KrakenServiceError("Kraken ticker payload missing close price")

        return float(close[0])

    def fetch_ohlc_close_prices(
        self,
        *,
        pair: str = "XBTUSD",
        interval_minutes: int = 5,
    ) -> list[KrakenOhlcSample]:
        response = requests.get(
            f"{self.base_url}/0/public/OHLC",
            params={"pair": pair, "interval": interval_minutes},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()

        if payload.get("error"):
            raise KrakenServiceError(f"Kraken OHLC error: {payload['error']}")

        result = payload.get("result") or {}
        if not result:
            raise KrakenServiceError("Kraken OHLC result is empty")

        pair_key = next((k for k in result.keys() if k != "last"), None)
        if not pair_key:
            raise KrakenServiceError("Kraken OHLC result missing pair data")

        rows = result.get(pair_key) or []
        samples: list[KrakenOhlcSample] = []

        for row in rows:
            if len(row) < 5:
                continue
            ts = int(row[0])
            close_price = float(row[4])
            samples.append(
                KrakenOhlcSample(
                    sampled_at=datetime.fromtimestamp(ts, tz=timezone.utc),
                    price_usd=close_price,
                )
            )

        return samples
