"""Contrato simple de precios para desacoplar cálculos del proveedor."""

from decimal import Decimal


class PriceRepository:
    """Almacén en memoria de precios manuales para la Fase 1."""

    def __init__(self, prices: dict[str, Decimal] | None = None) -> None:
        self._prices = {symbol.upper(): price for symbol, price in (prices or {}).items()}

    def set(self, symbol: str, price: Decimal) -> None:
        """Registra un precio positivo."""
        if price <= 0:
            raise ValueError("El precio debe ser mayor que cero.")
        self._prices[symbol.upper()] = price

    def get(self, symbol: str) -> Decimal | None:
        """Obtiene un precio, si existe."""
        return self._prices.get(symbol.upper())

