from datetime import datetime, timedelta

from .config import Settings
from .db import (
    close_with_sell,
    get_connection,
    get_hourly_metrics,
    get_last_buy_time,
    get_open_buys,
    get_wallet_summary,
    get_price_samples_window,
    insert_buy,
    BuyPosition,
    WalletSummary,
)
from .services.market.service import fetch_btc_price_chf
from .strategy import (
    TrendSignal,
    Decision,
    compute_dynamic_stop_loss,
    compute_wallet,
    evaluate_trend,
    evaluate_position,
    find_reinvest_candidate,
    is_crash_guard_active,
)


def run_cycle() -> None:
    """
    Execute one complete strategy cycle following exact order defined in AGENTS.md.
    
    Order:
    1. Fetch current price and hourly metrics
    2. Evaluate trend
    3. Evaluate open positions for sell triggers (stop-loss, take-profit, bearish exit)
    4. If any SELL executed → stop, skip buy evaluation
    5. Evaluate buy signal (trend, open positions, cooldown, crash guard)
    6. If buy signal fires:
       - If enough free_cash → place BUY
       - Else if profitable position exists → sell it, then place BUY
       - Else → skip
    """
    settings = Settings()
    conn = get_connection(settings.dsn)

    try:
        # === STEP 1: Fetch current price and hourly metrics ===
        current_price = fetch_btc_price_chf()
        hourly_metrics = get_hourly_metrics(
            conn,
            asset_symbol=settings.asset_symbol,
            hours=max(settings.trend_short_window_hours, settings.trend_long_window_hours) + 1,
        )
        
        # === STEP 2: Evaluate trend ===
        trend = evaluate_trend(
            hourly_metrics=hourly_metrics,
            short_window=settings.trend_short_window_hours,
            long_window=settings.trend_long_window_hours,
        )
        print(f"Trend: {trend.value}")

        # === STEP 3: Evaluate open positions for sell triggers ===
        open_positions = get_open_buys(conn, settings.asset_symbol)
        sell_executed = False
        
        if open_positions:
            # Compute dynamic stop-loss based on volatility
            dynamic_stop_loss = compute_dynamic_stop_loss(
                hourly_metrics=hourly_metrics,
                base_stop_loss_pct=settings.stop_loss_pct,
                atr_multiplier=settings.dynamic_stop_loss_atr_multiplier,
            )
            
            # Track bearish cycles for each position
            # Simple approach: count consecutive bearish in last N hourly metrics
            bearish_count = 0
            for metric in hourly_metrics[:settings.bearish_exit_min_cycles + 1]:
                # Micro-trend for this hour
                short_ma = metric.avg_price_usd  # Single data point acts as its own MA
                if metric.max_price_usd > metric.avg_price_usd:
                    # Price rising in this hour = bullish signal
                    bearish_count = 0
                else:
                    bearish_count += 1
                if bearish_count >= settings.bearish_exit_min_cycles:
                    break
            
            # Evaluate each position for sell triggers
            for position in open_positions:
                decision = evaluate_position(
                    position=position,
                    current_price_chf=current_price,
                    take_profit_pct=settings.take_profit_pct,
                    stop_loss_pct=dynamic_stop_loss,
                    trend=trend,
                    bearish_cycles=bearish_count,
                    bearish_exit_min_cycles=settings.bearish_exit_min_cycles,
                    enable_bearish_exit=getattr(settings, "enable_bearish_exit", False),
                    exchange_fee_rate=settings.exchange_fee_rate,
                )

                if decision.decision == Decision.SELL:
                    # Execute sell
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
                        f"change={decision.change_pct:.2f}%, reason={decision}"
                    )
                    sell_executed = True
                    break  # Only one action per cycle
                else:
                    print(
                        f"{decision.decision.value}: buy_id={position.id}, "
                        f"change={decision.change_pct:.2f}%"
                    )

        # === STEP 4: If sell executed, stop cycle ===
        if sell_executed:
            print("Cycle complete (sell was executed)")
            return

        # === STEP 5: Evaluate buy conditions ===
        # Condition 1: Trend must be BULLISH
        if trend != TrendSignal.BULLISH:
            print(f"BUY skipped: trend is {trend.value}, not BULLISH")
            return

        # Condition 2: Open positions < MAX_OPEN_POSITIONS
        if len(open_positions) >= settings.max_open_positions:
            print(f"BUY skipped: at max positions ({len(open_positions)} >= {settings.max_open_positions})")
            return

        # Condition 3: Time since last buy >= MIN_MINUTES_BETWEEN_TRADES
        last_buy_time = get_last_buy_time(conn, settings.asset_symbol)
        if last_buy_time:
            time_since_last_buy = datetime.now(datetime.now().astimezone().tzinfo) - last_buy_time
            if time_since_last_buy.total_seconds() / 60 < settings.min_minutes_between_trades:
                minutes_left = settings.min_minutes_between_trades - (time_since_last_buy.total_seconds() / 60)
                print(f"BUY skipped: cooldown active ({minutes_left:.0f} min remaining)")
                return

        # Condition 4: Crash guard not active
        price_samples = get_price_samples_window(
            conn,
            asset_symbol=settings.asset_symbol,
            lookback_days=90,
        )
        crash_window_minutes = 4 * settings.min_minutes_between_trades
        if is_crash_guard_active(price_samples, crash_window_minutes):
            print("BUY skipped: crash guard active")
            return

        # === STEP 6: Compute wallet and buy budget ===
        wallet_summary = get_wallet_summary(conn, settings.asset_symbol)
        free_cash, total_wallet = compute_wallet(
            net_deposits=wallet_summary.net_deposits,
            realized_pnl=wallet_summary.realized_pnl,
            open_positions_cost_basis=wallet_summary.open_cost_basis,
            open_positions_current_value=sum(p.quantity_btc * current_price for p in open_positions) 
                if open_positions else 0,
        )
        
        buy_budget = total_wallet * settings.wallet_fraction_per_trade
        
        print(f"Wallet: free_cash={free_cash:.2f}, total={total_wallet:.2f}, budget={buy_budget:.2f}")

        # === STEP 7: Execute buy or try reinvestment ===
        if free_cash >= buy_budget and buy_budget > 0:
            # Enough cash and positive budget: place BUY
            _place_buy(
                conn, settings, current_price, buy_budget
            )
        else:
            # Not enough cash: try to find profitable position to reinvest
            reinvest_candidate = find_reinvest_candidate(
                positions=open_positions,
                current_price=current_price,
                exchange_fee_rate=settings.exchange_fee_rate,
            )
            
            if reinvest_candidate:
                # Sell the candidate
                sell_notional = reinvest_candidate.quantity_btc * current_price
                sell_fee = sell_notional * settings.exchange_fee_rate
                sell_id = close_with_sell(
                    conn=conn,
                    buy_position=reinvest_candidate,
                    platform_name="internal-bot",
                    asset_symbol=settings.asset_symbol,
                    sell_unit_price_usd=current_price,
                    sell_fee_usd=sell_fee,
                    strategy_tag=settings.strategy_tag,
                )
                print(f"Reinvest: sold buy_id={reinvest_candidate.id} for cash")
                
                # Now place BUY
                _place_buy(
                    conn, settings, current_price, buy_budget
                )
            else:
                print("BUY skipped: not enough free cash and no reinvest candidate")
        
        print("Cycle complete")

    finally:
        conn.close()


def _place_buy(
    conn,
    settings: Settings,
    current_price: float,
    buy_budget: float,
) -> int:
    """Helper to place a buy order."""
    buy_fee = buy_budget * settings.exchange_fee_rate
    net_budget = buy_budget - buy_fee
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
        f"BUY executed: id={buy_id}, symbol={settings.asset_symbol}, "
        f"qty={buy_quantity:.8f}, price={current_price:.2f}, fee={buy_fee:.2f}"
    )
    
    return buy_id


if __name__ == "__main__":
    run_cycle()
