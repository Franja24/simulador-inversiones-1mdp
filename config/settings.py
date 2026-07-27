"""Configuración central cargada desde variables de entorno."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Valores configurables del sistema."""

    market_data_provider: str = "manual"
    historical_market_provider: str = "yahoo"
    database_url: str = "sqlite:///data/reto_actinver.db"
    default_initial_capital: float = Field(default=1_000_000, gt=0)
    default_currency: str = "MXN"
    max_position_weight: float = Field(default=0.50, gt=0, le=1)
    min_different_symbols: int = Field(default=5, ge=1)
    log_level: str = "INFO"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia cacheada de configuración."""
    settings = Settings()
    if settings.database_url.startswith("sqlite:///"):
        Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(
            parents=True, exist_ok=True
        )
    return settings
