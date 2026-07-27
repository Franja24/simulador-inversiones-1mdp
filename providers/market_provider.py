"""Contrato desacoplado para inteligencia de mercado."""

from abc import ABC, abstractmethod
from datetime import date

from domain.market import MarketBar, MarketQuote


class MarketProvider(ABC):
    """Interfaz para proveedores presentes y futuros."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Nombre estable del proveedor."""

    @property
    @abstractmethod
    def provider_version(self) -> str:
        """Versión del adaptador."""

    @property
    @abstractmethod
    def supported_markets(self) -> tuple[str, ...]:
        """Mercados declarados por el adaptador."""

    @abstractmethod
    def get_quote(self, symbol: str) -> MarketQuote:
        """Obtiene una cotización."""

    @abstractmethod
    def get_history(self, symbol: str, start: date, end: date) -> list[MarketBar]:
        """Obtiene velas en un rango inclusivo."""

    def get_multiple_quotes(self, symbols: list[str]) -> dict[str, MarketQuote]:
        """Obtiene cotizaciones conservando errores por símbolo en el caller."""
        return {symbol: self.get_quote(symbol) for symbol in symbols}

    def get_multiple_history(
        self, symbols: list[str], start: date, end: date
    ) -> dict[str, list[MarketBar]]:
        """Obtiene históricos de múltiples emisoras."""
        return {symbol: self.get_history(symbol, start, end) for symbol in symbols}

    @abstractmethod
    def is_market_open(self) -> bool:
        """Indica si el mercado principal está abierto."""

    def normalize_symbol(self, symbol: str) -> str:
        """Normaliza un símbolo según las reglas del proveedor."""
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("La emisora es obligatoria.")
        return normalized


class MarketProviderError(RuntimeError):
    """Error recuperable de un proveedor externo."""
