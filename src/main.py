from .config import Settings
from .db import close_with_sell, get_connection, get_open_buys, insert_buy
from .services.market.service import fetch_btc_price_usd
from .strategy import Decision, evaluate_position


def run_cycle() -> None:
    settings = Settings()
    conn = get_connection(settings.dsn)

    try:
        current_price = fetch_btc_price_usd()
        buy_fee = settings.buy_budget_usd * settings.exchange_fee_rate
        net_budget = settings.buy_budget_usd - buy_fee
        buy_quantity = net_budget / current_price

        buy_id = insert_buy(
            conn=conn,
            platform_name="internal-bot",
            asset_symbol=settings.asset_symbol,
            quantity_btc=buy_quantity,
            unit_price_usd=current_price,
            fee_usd=buy_fee,
            strategy_tag=settings.strategy_tag,
        )

        print(
            f"BUY recorded: id={buy_id}, symbol={settings.asset_symbol}, "
            f"qty={buy_quantity:.8f}, price={current_price:.2f}"
        )

        open_positions = get_open_buys(conn, settings.asset_symbol)
        if not open_positions:
            print("No open positions found.")
            return

        for position in open_positions:
            decision = evaluate_position(
                position=position,
                current_price_usd=current_price,
                take_profit_pct=settings.take_profit_pct,
                stop_loss_pct=settings.stop_loss_pct,
            )

            if decision.decision == Decision.SELL:
                sell_notional = position.quantity_btc * current_price
                sell_fee = sell_notional * settings.exchange_fee_rate
                sell_id = close_with_sell(
                    conn=conn,
                    buy_position=position,
                    platform_name="internal-bot",
                    asset_symbol=settings.asset_symbol,
                    sell_unit_price_usd=current_price,
                    sell_fee_usd=sell_fee,
                    strategy_tag=settings.strategy_tag,
                )
                print(
                    f"SELL executed: buy_id={position.id}, sell_id={sell_id}, "
                    f"change={decision.change_pct:.2f}%"
                )
            else:
                print(
                    f"{decision.decision.value}: buy_id={position.id}, "
                    f"change={decision.change_pct:.2f}%"
                )
    finally:
        conn.close()


if __name__ == "__main__":
    run_cycle()
