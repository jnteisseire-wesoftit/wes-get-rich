from dataclasses import dataclass
import os

from dotenv import load_dotenv


load_dotenv()


def _to_bool(value: str, default: bool) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(frozen=True)
class Settings:
    db_host: str = os.getenv("DB_HOST", "localhost")
    db_port: int = int(os.getenv("DB_PORT", "5432"))
    db_name: str = os.getenv("DB_NAME", "investor")
    db_user: str = os.getenv("DB_USER", "investor")
    db_password: str = os.getenv("DB_PASSWORD", "investor")

    asset_symbol: str = os.getenv("ASSET_SYMBOL", "BTC")
    exchange_fee_rate: float = float(os.getenv("EXCHANGE_FEE_RATE", "0.004"))
    
    # Strategy parameters (trend-v1)
    wallet_fraction_per_trade: float = float(os.getenv("WALLET_FRACTION_PER_TRADE", "0.10"))
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "10"))
    min_minutes_between_trades: int = int(os.getenv("MIN_MINUTES_BETWEEN_TRADES", "1440"))
    take_profit_pct: float = float(os.getenv("TAKE_PROFIT_PCT", "5.0"))
    stop_loss_pct: float = float(os.getenv("STOP_LOSS_PCT", "-2.0"))
    dynamic_stop_loss_atr_multiplier: float = float(os.getenv("DYNAMIC_STOP_LOSS_ATR_MULTIPLIER", "1.5"))
    trend_short_window_hours: int = int(os.getenv("TREND_SHORT_WINDOW_HOURS", "6"))
    trend_long_window_hours: int = int(os.getenv("TREND_LONG_WINDOW_HOURS", "24"))
    bearish_exit_min_cycles: int = int(os.getenv("BEARISH_EXIT_MIN_CYCLES", "2"))
    enable_bearish_exit: bool = _to_bool(os.getenv("ENABLE_BEARISH_EXIT", "false"), False)
    strategy_tag: str = os.getenv("STRATEGY_TAG", "trend-v1")
    enable_price_sampler: bool = _to_bool(os.getenv("ENABLE_PRICE_SAMPLER", "true"), True)
    price_sample_interval_seconds: int = int(os.getenv("PRICE_SAMPLE_INTERVAL_SECONDS", "300"))
    bot_cycle_interval_seconds: int = int(os.getenv("BOT_CYCLE_INTERVAL_SECONDS", "300"))
    auto_start_bot: bool = _to_bool(os.getenv("AUTO_START_BOT", "false"), False)
    strategy_history_source: str = os.getenv("STRATEGY_HISTORY_SOURCE", "db")
    strategy_metrics_window_hours: int = int(os.getenv("STRATEGY_METRICS_WINDOW_HOURS", "24"))
    kraken_history_lookback_days: int = int(os.getenv("KRAKEN_HISTORY_LOOKBACK_DAYS", "90"))
    kraken_history_interval_minutes: int = int(os.getenv("KRAKEN_HISTORY_INTERVAL_MINUTES", "5"))

    binance_base_url: str = os.getenv("BINANCE_BASE_URL", "https://api.binance.com")
    binance_api_key: str = os.getenv("BINANCE_API_KEY", "")
    binance_api_secret: str = os.getenv("BINANCE_API_SECRET", "")
    kraken_base_url: str = os.getenv("KRAKEN_BASE_URL", "https://api.kraken.com")
    kraken_trading_pair: str = os.getenv("KRAKEN_TRADING_PAIR", "XBTCHF")
    kraken_api_key: str = os.getenv("KRAKEN_API_KEY", "")
    kraken_api_secret: str = os.getenv("KRAKEN_API_SECRET", "")
    live_trading_enabled: bool = _to_bool(os.getenv("LIVE_TRADING_ENABLED", "false"), False)

    @property
    def dsn(self) -> str:
        return (
            f"host={self.db_host} "
            f"port={self.db_port} "
            f"dbname={self.db_name} "
            f"user={self.db_user} "
            f"password={self.db_password}"
        )
