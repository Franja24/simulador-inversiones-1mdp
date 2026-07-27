"""Soporte histórico configurable para benchmarks."""

from datetime import date

import pandas as pd
from sqlalchemy.orm import Session

from providers.market_provider import MarketProvider
from services.history_service import HistoryService


class BenchmarkService:
    """Administra un índice usando la misma infraestructura histórica."""

    DEFAULT_BENCHMARK = "^MXX"

    def __init__(self, session: Session, provider: MarketProvider) -> None:
        self.history = HistoryService(session, provider)

    def update(self, symbol: str, start: date, end: date) -> int:
        """Actualiza el benchmark configurado."""
        return self.history.update_symbol(symbol or self.DEFAULT_BENCHMARK, start, end)

    def load(self, symbol: str = DEFAULT_BENCHMARK) -> pd.DataFrame:
        """Carga precios y retornos del benchmark desde SQLite."""
        frame = self.history.load_history(symbol)
        if not frame.empty:
            frame["benchmark_return"] = frame["adj_close"].pct_change()
        return frame
