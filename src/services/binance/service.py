import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests


class BinanceServiceError(Exception):
    pass


@dataclass(frozen=True)
class BinanceCredentials:
    api_key: str
    api_secret: str


class BinanceService:
    def __init__(self, *, base_url: str, credentials: BinanceCredentials | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.credentials = credentials

    def get_symbol_price(self, symbol: str) -> float:
        payload = self._request_public("GET", "/api/v3/ticker/price", {"symbol": symbol.upper()})
        return float(payload["price"])

    def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float | None,
        quote_order_qty: float | None,
        test_order: bool,
    ) -> dict[str, Any]:
        if quantity is None and quote_order_qty is None:
            raise BinanceServiceError("Either quantity or quote_order_qty must be provided")

        params: dict[str, Any] = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": "MARKET",
            "recvWindow": 5000,
            "timestamp": int(time.time() * 1000),
        }

        if quantity is not None:
            params["quantity"] = quantity

        if quote_order_qty is not None:
            params["quoteOrderQty"] = quote_order_qty

        endpoint = "/api/v3/order/test" if test_order else "/api/v3/order"
        return self._request_signed("POST", endpoint, params)

    def _request_public(self, method: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = requests.request(method=method, url=url, params=params, timeout=15)

        if not response.ok:
            raise BinanceServiceError(f"Binance error: {response.status_code} {response.text}")

        return response.json()

    def _request_signed(self, method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.credentials is None:
            raise BinanceServiceError("Binance credentials are not configured")

        query = urlencode(params)
        signature = hmac.new(
            self.credentials.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        signed_params = dict(params)
        signed_params["signature"] = signature

        url = f"{self.base_url}{path}"
        response = requests.request(
            method=method,
            url=url,
            params=signed_params,
            headers={"X-MBX-APIKEY": self.credentials.api_key},
            timeout=15,
        )

        if not response.ok:
            raise BinanceServiceError(f"Binance error: {response.status_code} {response.text}")

        return response.json() if response.text else {}
