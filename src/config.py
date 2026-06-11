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
    buy_budget_usd: float = float(os.getenv("BUY_BUDGET_USD", "50"))
    exchange_fee_rate: float = float(os.getenv("EXCHANGE_FEE_RATE", "0.001"))
    take_profit_pct: float = float(os.getenv("TAKE_PROFIT_PCT", "5"))
    stop_loss_pct: float = float(os.getenv("STOP_LOSS_PCT", "-3"))
    strategy_tag: str = os.getenv("STRATEGY_TAG", "dca-v1")
    enable_price_sampler: bool = _to_bool(os.getenv("ENABLE_PRICE_SAMPLER", "true"), True)
    price_sample_interval_seconds: int = int(os.getenv("PRICE_SAMPLE_INTERVAL_SECONDS", "300"))
    strategy_history_source: str = os.getenv("STRATEGY_HISTORY_SOURCE", "db")
    strategy_metrics_window_hours: int = int(os.getenv("STRATEGY_METRICS_WINDOW_HOURS", "24"))

    binance_base_url: str = os.getenv("BINANCE_BASE_URL", "https://api.binance.com")
    binance_api_key: str = os.getenv("BINANCE_API_KEY", "")
    binance_api_secret: str = os.getenv("BINANCE_API_SECRET", "")
    kraken_base_url: str = os.getenv("KRAKEN_BASE_URL", "https://api.kraken.com")

    @property
    def dsn(self) -> str:
        return (
            f"host={self.db_host} "
            f"port={self.db_port} "
            f"dbname={self.db_name} "
            f"user={self.db_user} "
            f"password={self.db_password}"
        )
