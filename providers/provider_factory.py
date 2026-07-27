"""Fábrica central para seleccionar proveedores sin acoplar la UI."""

from sqlalchemy.orm import Session

from providers.cache_provider import CacheProvider
from providers.future_provider import FutureProvider
from providers.market_provider import MarketProvider
from providers.yahoo_provider import YahooProvider
from repositories.market_history_repository import MarketHistoryRepository


def create_market_provider(name: str, session: Session) -> MarketProvider:
    """Crea el proveedor configurado o falla con un mensaje claro."""
    normalized = name.strip().lower()
    if normalized == "yahoo":
        return YahooProvider()
    if normalized == "cache":
        return CacheProvider(MarketHistoryRepository(session))
    if normalized == "future":
        return FutureProvider()
    raise ValueError(f"Proveedor histórico no soportado: {name}.")
