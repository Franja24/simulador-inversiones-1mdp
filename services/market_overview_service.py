"""Resumen operacional para el dashboard de mercado."""

from datetime import UTC, datetime

import pandas as pd
from sqlalchemy.orm import Session

from providers.cache_provider import CacheProvider
from providers.market_provider import MarketProvider
from repositories.market_history_repository import MarketHistoryRepository
from services.market_session_service import BMVSessionService
from utils.dates import is_stale_price


class MarketOverviewService:
    """Prepara datos de UI sin cálculos financieros en Streamlit."""

    def __init__(
        self,
        session: Session,
        provider: MarketProvider,
        market_session: BMVSessionService | None = None,
    ) -> None:
        self.repository = MarketHistoryRepository(session)
        self.provider = provider
        self.cache = CacheProvider(self.repository)
        self.market_session = market_session or BMVSessionService()

    def summary(self) -> dict[str, object]:
        """Devuelve el estado agregado de mercado y cache."""
        latest = self.repository.latest_sync()
        return {
            "market_open": self.market_session.is_open(),
            "provider": self.provider.provider_name,
            "provider_version": self.provider.provider_version,
            "symbols": len(self.repository.symbols()),
            "rows": self.repository.count(),
            "last_sync": latest.created_at if latest else None,
            "recent_errors": len(self.repository.recent_errors()),
        }

    def symbol_table(self) -> pd.DataFrame:
        """Construye una tabla con la última vela cacheada por símbolo."""
        rows: list[dict[str, object]] = []
        for symbol in self.repository.symbols():
            quote = self.cache.get_quote(symbol)
            change = (
                (quote.price / quote.previous_close - 1) * 100
                if quote.previous_close
                else None
            )
            rows.append(
                {
                    "Símbolo": symbol,
                    "Último precio": quote.price,
                    "Variación diaria (%)": change,
                    "Volumen": quote.volume,
                    "Última fecha": quote.timestamp.date(),
                    "Estado cache": (
                        "RETRASADO"
                        if is_stale_price(quote.timestamp, datetime.now(UTC))
                        else "DISPONIBLE"
                    ),
                }
            )
        return pd.DataFrame(rows)

    def batch_quotes(
        self, symbols: list[str]
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        """Convierte resultados parciales del proveedor para la UI."""
        result = self.provider.get_multiple_quotes(symbols)
        return (
            pd.DataFrame(
                [
                    {
                        "Símbolo": symbol,
                        "Precio": quote.price,
                        "Cierre anterior": quote.previous_close,
                        "Volumen": quote.volume,
                        "Proveedor": quote.provider,
                        "Fecha": quote.timestamp,
                    }
                    for symbol, quote in result.successes.items()
                ]
            ),
            result.errors,
        )

    def recent_errors(self) -> pd.DataFrame:
        """Lista errores recientes sin trazas sensibles."""
        return pd.DataFrame(
            [
                {
                    "Símbolo": item.symbol,
                    "Proveedor": item.provider,
                    "Error": item.error_message,
                    "Fecha": item.created_at,
                }
                for item in self.repository.recent_errors()
            ]
        )
