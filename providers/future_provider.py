"""Contrato demostrativo para integrar proveedores posteriores."""

from datetime import date

from domain.market import MarketBar, MarketQuote
from providers.market_provider import MarketProvider, MarketProviderError


class FutureProvider(MarketProvider):
    """Proveedor intencionalmente no configurado, con errores explícitos."""

    @property
    def provider_name(self) -> str:
        return "future"

    @property
    def provider_version(self) -> str:
        return "0"

    @property
    def supported_markets(self) -> tuple[str, ...]:
        return ()

    def get_quote(self, symbol: str) -> MarketQuote:
        raise MarketProviderError(f"No hay proveedor futuro configurado para {symbol}.")

    def get_history(self, symbol: str, start: date, end: date) -> list[MarketBar]:
        raise MarketProviderError(f"No hay proveedor futuro configurado para {symbol}.")
