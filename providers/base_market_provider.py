"""Contrato para proveedores de precios."""

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal


class BaseMarketProvider(ABC):
    """Interfaz común para proveedores actuales y futuros."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Nombre visible del proveedor."""

    @abstractmethod
    def get_current_price(self, symbol: str) -> Decimal | None:
        """Obtiene el precio más reciente."""

    @abstractmethod
    def get_multiple_prices(self, symbols: list[str]) -> dict[str, Decimal | None]:
        """Obtiene varios precios."""

    @abstractmethod
    def get_last_update_time(self, symbol: str) -> datetime | None:
        """Obtiene la fecha de actualización más reciente."""

    @abstractmethod
    def save_price(
        self,
        symbol: str,
        price: Decimal,
        price_date: datetime,
        notes: str | None = None,
    ) -> None:
        """Guarda una observación de precio."""

