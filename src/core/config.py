from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    allowed_origins: list[str] = ["http://localhost:3000"]
    trading_mode: str = "paper"
    autonomy_mode: str = "COMMANDER"
    max_risk_per_trade: float = 0.02
    max_daily_loss: float = 0.05


settings = Settings()
