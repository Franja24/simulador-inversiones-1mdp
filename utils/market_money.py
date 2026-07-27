"""Frontera única entre floats de mercado y Decimal contable."""

from decimal import Decimal


def market_price_to_decimal(price: float) -> Decimal:
    """Convierte mediante texto para evitar artefactos binarios.

    Históricos e indicadores usan ``float``; operaciones, efectivo, costo y
    valoración monetaria usan ``Decimal``.
    """
    if price <= 0:
        raise ValueError("El precio de mercado debe ser mayor que cero.")
    return Decimal(str(price))
