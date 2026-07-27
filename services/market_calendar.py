"""Calendarios de sesiones esperadas desacoplados de proveedores."""

from datetime import date
from typing import Protocol

import pandas as pd


class MarketCalendar(Protocol):
    """Contrato mínimo de calendario bursátil."""

    def expected_sessions(self, start: date, end: date) -> set[date]:
        """Devuelve sesiones esperadas dentro del rango."""
        ...


class WeekdayMarketCalendar:
    """Calendario lunes-viernes con exclusiones inyectables.

    No incluye todavía el calendario oficial completo de festivos de la BMV.
    """

    def __init__(self, non_trading_dates: set[date] | None = None) -> None:
        self.non_trading_dates = non_trading_dates or set()

    def expected_sessions(self, start: date, end: date) -> set[date]:
        if end < start:
            raise ValueError("La fecha final no puede ser anterior a la inicial.")
        return {
            timestamp.date()
            for timestamp in pd.bdate_range(start=start, end=end)
            if timestamp.date() not in self.non_trading_dates
        }

