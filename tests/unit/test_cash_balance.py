from decimal import Decimal

from src.api import (
    _compute_cash_balance,
    _compute_open_invested,
    _extract_live_cash_balance,
    _extract_live_btc_balance,
)


def test_cash_balance_uses_quote_currency_flows_and_fees() -> None:
    rows = [
        {"action": "DEPOSIT", "quantity_btc": Decimal("1"), "unit_price_usd": Decimal("200"), "fee_usd": Decimal("1")},
        {"action": "BUY", "quantity_btc": Decimal("0.25"), "unit_price_usd": Decimal("200"), "fee_usd": Decimal("0.50")},
        {"action": "SELL", "quantity_btc": Decimal("0.10"), "unit_price_usd": Decimal("220"), "fee_usd": Decimal("0.22")},
        {"action": "WITHDRAWAL", "quantity_btc": Decimal("0.10"), "unit_price_usd": Decimal("220"), "fee_usd": Decimal("0.10")},
    ]

    assert _compute_cash_balance(rows) == 148.18


def test_live_cash_balance_prefers_chf_wallet_symbol() -> None:
    assert _extract_live_cash_balance({"CHF": 142.05, "XXBT": 0.00099258}) == 142.05
    assert _extract_live_cash_balance({"ZCHF": 142.05}) == 142.05
    assert _extract_live_cash_balance({"XXBT": 0.00099258}) is None


def test_open_invested_excludes_closed_buy_transactions() -> None:
    rows = [
        {"action": "BUY", "status": "CLOSED", "quantity_btc": Decimal("1"), "unit_price_usd": Decimal("200"), "fee_usd": Decimal("1")},
        {"action": "BUY", "status": "OPEN", "quantity_btc": Decimal("0.25"), "unit_price_usd": Decimal("200"), "fee_usd": Decimal("0.50")},
    ]

    assert _compute_open_invested(rows) == 50.5


def test_live_btc_balance_accepts_kraken_asset_symbols() -> None:
    assert _extract_live_btc_balance({"CHF": 142.05, "XXBT": 0.00099258}) == 0.00099258
    assert _extract_live_btc_balance({"XBT": 0.1}) == 0.1
    assert _extract_live_btc_balance({"CHF": 142.05}) == 0.0