"""Funciones puras de cálculo financiero."""

from decimal import Decimal


def percentage_change(value: Decimal, base: Decimal) -> Decimal:
    """Calcula cambio porcentual; devuelve cero cuando no hay base."""
    return Decimal("0") if base == 0 else (value - base) / base * Decimal("100")


def maximum_drawdown(values: list[Decimal]) -> Decimal:
    """Calcula el drawdown máximo porcentual de una serie."""
    if not values:
        return Decimal("0")
    peak = values[0]
    worst = Decimal("0")
    for value in values:
        peak = max(peak, value)
        if peak:
            worst = min(worst, (value - peak) / peak * Decimal("100"))
    return worst

