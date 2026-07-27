"""Administración incremental de históricos de mercado."""

from datetime import date, timedelta

import pandas as pd
from sqlalchemy.orm import Session

from providers.market_provider import MarketProvider
from repositories.market_history_repository import MarketHistoryRepository


class HistoryService:
    """Sincroniza proveedores externos con el cache SQLite."""

    def __init__(self, session: Session, provider: MarketProvider) -> None:
        self.session = session
        self.provider = provider
        self.repository = MarketHistoryRepository(session)

    def update_symbol(self, symbol: str, start: date, end: date) -> int:
        """Descarga solo intervalos con fechas hábiles ausentes."""
        normalized = self.provider.normalize_symbol(symbol)
        missing = self.missing_dates(normalized, start, end)
        if not missing:
            return 0
        total = 0
        try:
            for range_start, range_end in self._contiguous_ranges(missing):
                bars = self.provider.get_history(
                    normalized, range_start, range_end
                )
                total += self.repository.upsert_many(bars)
            self.repository.save_sync(
                normalized, self.provider.provider_name, "OK", total
            )
            self.session.commit()
            return total
        except Exception as exc:
            self.session.rollback()
            self.repository.save_sync(
                normalized,
                self.provider.provider_name,
                "ERROR",
                0,
                type(exc).__name__,
            )
            self.session.commit()
            raise

    def update_all(
        self, symbols: list[str], start: date, end: date
    ) -> dict[str, int]:
        """Actualiza múltiples símbolos sin detenerse por un error aislado."""
        result: dict[str, int] = {}
        for symbol in symbols:
            try:
                result[symbol] = self.update_symbol(symbol, start, end)
            except Exception:
                result[symbol] = 0
        return result

    def load_history(
        self, symbol: str, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame:
        """Carga datos locales ordenados y sin depender de Internet."""
        rows = self.repository.list_history(symbol, start, end)
        columns = [
            "date",
            "open",
            "high",
            "low",
            "close",
            "adj_close",
            "volume",
            "dividends",
            "stock_splits",
            "timezone",
            "provider",
        ]
        return pd.DataFrame(
            [
                {
                    "date": row.date,
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "adj_close": row.adj_close,
                    "volume": row.volume,
                    "dividends": row.dividends,
                    "stock_splits": row.stock_splits,
                    "timezone": row.timezone,
                    "provider": row.provider,
                }
                for row in rows
            ],
            columns=columns,
        )

    def last_available_date(self, symbol: str) -> date | None:
        """Obtiene la última sesión guardada."""
        return self.repository.last_date(symbol)

    def missing_dates(self, symbol: str, start: date, end: date) -> list[date]:
        """Detecta huecos de lunes a viernes.

        No descuenta todavía festivos bursátiles, por lo que estos pueden aparecer
        como huecos informativos.
        """
        if end < start:
            raise ValueError("La fecha final no puede ser anterior a la inicial.")
        expected = {
            timestamp.date()
            for timestamp in pd.bdate_range(start=start, end=end)
        }
        return sorted(expected - self.repository.dates(symbol, start, end))

    def refresh_if_needed(self, symbol: str, start: date, end: date) -> int:
        """Actualiza únicamente si existe al menos una fecha hábil faltante."""
        return self.update_symbol(symbol, start, end) if self.missing_dates(
            symbol, start, end
        ) else 0

    @staticmethod
    def _contiguous_ranges(dates: list[date]) -> list[tuple[date, date]]:
        if not dates:
            return []
        ranges: list[tuple[date, date]] = []
        start = previous = dates[0]
        for current in dates[1:]:
            cursor = previous + timedelta(days=1)
            while cursor.weekday() >= 5:
                cursor += timedelta(days=1)
            if current != cursor:
                ranges.append((start, previous))
                start = current
            previous = current
        ranges.append((start, previous))
        return ranges
