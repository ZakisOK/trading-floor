from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        default="postgresql+asyncpg://tradingfloor:tradingfloor_dev@localhost:5432/tradingfloor"
    )
    questdb_host: str = "localhost"
    questdb_ilp_port: int = 9009
    questdb_http_port: int = 9000
    redis_url: str = "redis://localhost:6379/0"
    anthropic_api_key: str = ""
    environment: str = "development"
    log_level: str = "INFO"
    secret_key: str = "change_me"
    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    trading_mode: str = "paper"
    autonomy_mode: str = "COMMANDER"
    max_risk_per_trade: float = 0.02
    max_daily_loss: float = 0.05

    # News & Sentiment
    news_api_key: str = ""              # NewsAPI.org free tier (100 req/day); blank → RSS fallback
    sentiment_backend: str = "vader"    # "finbert" or "vader"; auto-downgrades if deps missing

    # Market data enrichment
    fred_api_key: str = ""
    eia_api_key: str = ""

    # XRPL on-chain tracking
    xrpl_whale_tracking: bool = True

    # Copy trading
    binance_leaderboard_enabled: bool = True
    copy_trade_min_confidence: float = 0.65

    # Position & risk monitoring intervals
    position_monitor_interval_seconds: int = 5
    risk_monitor_interval_seconds: int = 30
    trailing_stop_trigger_pct: float = 0.05

    # Alpaca MCP + broker
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    alpaca_paper_trade: bool = True
    alpaca_toolsets: str = (
        "account,positions,stock_data,crypto_data,options_data,watchlists,assets,news"
    )

    # DigitalOcean MCP
    digitalocean_api_token: str = ""

    # Memory / Learning Stack
    graphiti_url: str = "http://graphiti:8000"
    zep_api_secret: str = "change_me_local_only"
    openai_api_key: str = ""
    phoenix_collector_endpoint: str = "http://phoenix:6006"

    # Neo4j (Graphiti backend)
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "change_me_local_only"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_allowed_origins(cls, v: object) -> object:
        """Accept comma-separated strings in addition to JSON arrays."""
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                return v
            return [origin.strip() for origin in s.split(",") if origin.strip()]
        return v


settings = Settings()
