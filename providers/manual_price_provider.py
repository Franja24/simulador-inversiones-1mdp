"""Proveedor manual respaldado por SQLite."""

from datetime import datetime
from decimal import Decimal

from database.models import ManualPriceModel
from providers.base_market_provider import BaseMarketProvider
from repositories.price_repository import SqlPriceRepository


class ManualPriceProvider(BaseMarketProvider):
    """Guarda y consulta capturas manuales sin llamadas externas."""

    def __init__(self, repository: SqlPriceRepository) -> None:
        self.repository = repository

    @property
    def provider_name(self) -> str:
        """Nombre visible del proveedor."""
        return "manual"

    def get_current_price(self, symbol: str) -> Decimal | None:
        """Obtiene el último precio."""
        return self.repository.get(symbol)

    def get_multiple_prices(self, symbols: list[str]) -> dict[str, Decimal | None]:
        """Obtiene precios normalizando símbolos."""
        return {
            symbol.strip().upper(): self.get_current_price(symbol)
            for symbol in symbols
        }

    def get_last_update_time(self, symbol: str) -> datetime | None:
        """Obtiene la fecha del último precio."""
        return self.repository.get_last_update_time(symbol)

    def save_price(
        self,
        symbol: str,
        price: Decimal,
        price_date: datetime,
        notes: str | None = None,
    ) -> None:
        """Persiste una captura validada."""
        if price <= 0:
            raise ValueError("El precio debe ser mayor que cero.")
        if not symbol.strip():
            raise ValueError("La emisora es obligatoria.")
        self.repository.add(
            ManualPriceModel(
                symbol=symbol.strip().upper(),
                price=price,
                price_date=price_date,
                provider=self.provider_name,
                notes=notes,
            )
        )

