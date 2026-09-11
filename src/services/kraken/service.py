import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import time
from urllib.parse import urlencode

import requests


@dataclass
class KrakenOhlcSample:
    sampled_at: datetime
    price_usd: float


@dataclass
class KrakenOhlcBatch:
    samples: list[KrakenOhlcSample]
    last: int


@dataclass
class KrakenTrade:
    traded_at: datetime
    price_usd: float


@dataclass
class KrakenTradesBatch:
    trades: list[KrakenTrade]
    last: int


@dataclass
class KrakenLedgerEntry:
    """Represents a deposit or withdrawal from Kraken ledger"""
    ref_id: str
    entry_type: str  # 'deposit' or 'withdrawal'
    asset: str
    amount: float
    fee: float
    timestamp: datetime


class KrakenServiceError(RuntimeError):
    pass


class KrakenService:
    def __init__(
        self,
        base_url: str = "https://api.kraken.com",
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.api_secret = api_secret or ""

    def _request_private(self, path: str, payload: dict[str, str] | None = None) -> dict:
        if not self.api_key or not self.api_secret:
            raise KrakenServiceError("Kraken API credentials are required for private endpoints")

        nonce = str(int(time.time() * 1000))
        body = payload.copy() if payload else {}
        body["nonce"] = nonce

        postdata = urlencode(body)
        encoded = (nonce + postdata).encode("utf-8")
        message = path.encode("utf-8") + hashlib.sha256(encoded).digest()

        try:
            secret = base64.b64decode(self.api_secret)
        except Exception as exc:  # pragma: no cover - defensive validation
            raise KrakenServiceError("Kraken API secret is not valid base64") from exc

        signature = hmac.new(secret, message, hashlib.sha512)
        headers = {
            "API-Key": self.api_key,
            "API-Sign": base64.b64encode(signature.digest()).decode("utf-8"),
        }

        response = requests.post(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("error"):
            raise KrakenServiceError(f"Kraken private API error: {data['error']}")

        return data.get("result") or {}

    def fetch_balances(self) -> dict[str, float]:
        result = self._request_private("/0/private/Balance")
        balances: dict[str, float] = {}

        for asset, amount in result.items():
            try:
                balances[asset] = float(amount)
            except (TypeError, ValueError):
                continue

        return balances

    def place_market_order(
        self,
        *,
        pair: str,
        side: str,
        volume: float,
        quote_volume: float | None = None,
        validate_only: bool = True,
    ) -> dict:
        side_normalized = side.lower()
        if side_normalized not in {"buy", "sell"}:
            raise KrakenServiceError("Kraken order side must be BUY or SELL")
        if volume <= 0:
            raise KrakenServiceError("Kraken order volume must be greater than zero")
        if quote_volume is not None and quote_volume <= 0:
            raise KrakenServiceError("Kraken quote order volume must be greater than zero")
        if quote_volume is not None and side_normalized != "buy":
            raise KrakenServiceError("Kraken quote order volume is only supported for BUY orders")

        payload = {
            "pair": pair,
            "type": side_normalized,
            "ordertype": "market",
            "volume": f"{(quote_volume if quote_volume is not None else volume):.8f}",
        }
        if quote_volume is not None:
            payload["oflags"] = "viqc"
        if validate_only:
            payload["validate"] = "true"

        return self._request_private("/0/private/AddOrder", payload=payload)

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
        since_epoch: int | None = None,
    ) -> list[KrakenOhlcSample]:
        batch = self.fetch_ohlc_close_prices_batch(
            pair=pair,
            interval_minutes=interval_minutes,
            since_epoch=since_epoch,
        )
        return batch.samples

    def fetch_ohlc_close_prices_batch(
        self,
        *,
        pair: str = "XBTUSD",
        interval_minutes: int = 5,
        since_epoch: int | None = None,
    ) -> KrakenOhlcBatch:
        params: dict[str, int | str] = {"pair": pair, "interval": interval_minutes}
        if since_epoch is not None:
            params["since"] = since_epoch

        response = requests.get(
            f"{self.base_url}/0/public/OHLC",
            params=params,
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
        last_raw = result.get("last")
        if last_raw is None:
            raise KrakenServiceError("Kraken OHLC result missing last cursor")

        try:
            last = int(last_raw)
        except (TypeError, ValueError) as exc:
            raise KrakenServiceError("Kraken OHLC result has invalid last cursor") from exc

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

        return KrakenOhlcBatch(samples=samples, last=last)

    def fetch_trades_batch(
        self,
        *,
        pair: str = "XBTUSD",
        since_cursor: int | None = None,
    ) -> KrakenTradesBatch:
        params: dict[str, int | str] = {"pair": pair}
        if since_cursor is not None:
            params["since"] = since_cursor

        response = requests.get(
            f"{self.base_url}/0/public/Trades",
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()

        if payload.get("error"):
            raise KrakenServiceError(f"Kraken trades error: {payload['error']}")

        result = payload.get("result") or {}
        if not result:
            raise KrakenServiceError("Kraken trades result is empty")

        pair_key = next((k for k in result.keys() if k != "last"), None)
        if not pair_key:
            raise KrakenServiceError("Kraken trades result missing pair data")

        last_raw = result.get("last")
        if last_raw is None:
            raise KrakenServiceError("Kraken trades result missing last cursor")

        try:
            last = int(last_raw)
        except (TypeError, ValueError) as exc:
            raise KrakenServiceError("Kraken trades result has invalid last cursor") from exc

        rows = result.get(pair_key) or []
        trades: list[KrakenTrade] = []

        for row in rows:
            if len(row) < 3:
                continue
            price = float(row[0])
            traded_at = datetime.fromtimestamp(float(row[2]), tz=timezone.utc)
            trades.append(KrakenTrade(traded_at=traded_at, price_usd=price))

        return KrakenTradesBatch(trades=trades, last=last)

    def fetch_ledger_entries(self) -> list[KrakenLedgerEntry]:
        """Fetch deposit and withdrawal history from Kraken ledger.
        
        Requires 'Query Ledger' permission on the API key.
        """
        result = self._request_private("/0/private/Ledger")
        
        entries: list[KrakenLedgerEntry] = []
        
        for ref_id, entry_data in result.items():
            try:
                entry_type = entry_data.get("type", "").lower()
                if entry_type not in {"deposit", "withdrawal"}:
                    continue
                
                entries.append(
                    KrakenLedgerEntry(
                        ref_id=ref_id,
                        entry_type=entry_type,
                        asset=entry_data.get("asset", ""),
                        amount=float(entry_data.get("amount", 0)),
                        fee=float(entry_data.get("fee", 0)),
                        timestamp=datetime.fromtimestamp(
                            float(entry_data.get("time", 0)),
                            tz=timezone.utc
                        ),
                    )
                )
            except (TypeError, ValueError, KeyError):
                continue
        
        return sorted(entries, key=lambda e: e.timestamp)
