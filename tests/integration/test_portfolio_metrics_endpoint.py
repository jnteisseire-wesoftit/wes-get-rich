from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from src import api


def test_portfolio_metrics_endpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    dummy_conn,
) -> None:
    now = datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc)

    # Mock transactions: 1 open BUY, 1 closed BUY+SELL
    rows = [
        # Closed pair
        {
            "id": 2,
            "platform_name": "kraken",
            "asset_symbol": "BTC",
            "action": "SELL",
            "quantity_btc": Decimal("0.001"),
            "unit_price_usd": Decimal("68500.00"),
            "fee_usd": Decimal("0.70"),
            "paired_buy_transaction_id": 1,
            "realized_pnl_usd": Decimal("200.00"),
            "status": "CLOSED",
            "transaction_at": now,
            "strategy_tag": "test",
            "notes": None,
            "executed_at": now,
            "created_at": now,
        },
        {
            "id": 1,
            "platform_name": "kraken",
            "asset_symbol": "BTC",
            "action": "BUY",
            "quantity_btc": Decimal("0.001"),
            "unit_price_usd": Decimal("67000.00"),
            "fee_usd": Decimal("0.67"),
            "paired_buy_transaction_id": None,
            "realized_pnl_usd": None,
            "status": "CLOSED",
            "transaction_at": now,
            "strategy_tag": "test",
            "notes": None,
            "executed_at": now,
            "created_at": now,
        },
        # Open position
        {
            "id": 3,
            "platform_name": "kraken",
            "asset_symbol": "BTC",
            "action": "BUY",
            "quantity_btc": Decimal("0.002"),
            "unit_price_usd": Decimal("67500.00"),
            "fee_usd": Decimal("1.35"),
            "paired_buy_transaction_id": None,
            "realized_pnl_usd": None,
            "status": "OPEN",
            "transaction_at": now,
            "strategy_tag": "test",
            "notes": None,
            "executed_at": now,
            "created_at": now,
        },
    ]

    monkeypatch.setattr(api, "get_connection", lambda _dsn: dummy_conn)
    monkeypatch.setattr(api, "list_transactions", lambda *_args, **_kwargs: rows)
    monkeypatch.setattr(api, "fetch_btc_price_usd", lambda: 68000.0)

    response = client.get("/portfolio/metrics?asset_symbol=BTC")

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_symbol"] == "BTC"
    assert payload["current_price_usd"] == 68000.0
    assert payload["exchange_fee_rate"] == 0.001
    
    # total_invested = 67000 + 0.67 + 67500*2 + 1.35 = 202001.35
    assert payload["total_invested_usd"] == pytest.approx(202001.02, abs=1)
    
    # Realized profit from closed trade = 200
    assert payload["total_realized_profit_usd"] == 200.0
    assert payload["total_realized_loss_usd"] == 0.0
    
    # Fees paid = 0.67 + 0.70 + 1.35 = 2.72
    assert payload["total_fees_paid_usd"] == pytest.approx(2.72, abs=0.01)
    
    # Open position: 0.002 BTC at 68000 = 136 USD
    # Net PnL after exit fees = 136 - (67500*2 + 1.35) - 136*0.001
    # = 136 - 135001.35 - 0.136 = -134865...
    assert len(payload["open_positions"]) == 1
    assert payload["open_positions"][0]["transaction_id"] == 3
    assert payload["open_positions"][0]["quantity_btc"] == 0.002
    
    assert dummy_conn.closed is True
