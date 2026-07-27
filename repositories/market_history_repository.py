"""Persistencia de históricos, indicadores y sincronizaciones."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.models import (
    IndicatorCacheModel,
    MarketHistoryModel,
    MarketSyncLogModel,
)
from domain.market import MarketBar


class MarketHistoryRepository:
    """Repositorio de velas diarias sin dependencia del proveedor externo."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, bars: list[MarketBar]) -> int:
        """Inserta únicamente fechas ausentes y devuelve filas nuevas."""
        if not bars:
            return 0
        symbol = bars[0].symbol
        dates = {bar.date for bar in bars}
        existing = set(
            self.session.scalars(
                select(MarketHistoryModel.date).where(
                    MarketHistoryModel.symbol == symbol,
                    MarketHistoryModel.date.in_(dates),
                )
            )
        )
        new_bars = [bar for bar in bars if bar.date not in existing]
        self.session.add_all(
            [
                MarketHistoryModel(
                    symbol=bar.symbol,
                    date=bar.date,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    adj_close=bar.adj_close,
                    volume=bar.volume,
                    dividends=bar.dividends,
                    stock_splits=bar.stock_splits,
                    timezone=bar.timezone,
                    provider=bar.provider,
                )
                for bar in new_bars
            ]
        )
        self.session.flush()
        return len(new_bars)

    def list_history(
        self, symbol: str, start: date | None = None, end: date | None = None
    ) -> list[MarketHistoryModel]:
        """Lista velas ordenadas y opcionalmente acotadas."""
        statement = select(MarketHistoryModel).where(
            MarketHistoryModel.symbol == symbol.strip().upper()
        )
        if start is not None:
            statement = statement.where(MarketHistoryModel.date >= start)
        if end is not None:
            statement = statement.where(MarketHistoryModel.date <= end)
        return list(self.session.scalars(statement.order_by(MarketHistoryModel.date)))

    def dates(self, symbol: str, start: date, end: date) -> set[date]:
        """Devuelve las fechas almacenadas en un intervalo."""
        return set(
            self.session.scalars(
                select(MarketHistoryModel.date).where(
                    MarketHistoryModel.symbol == symbol.strip().upper(),
                    MarketHistoryModel.date >= start,
                    MarketHistoryModel.date <= end,
                )
            )
        )

    def last_date(self, symbol: str) -> date | None:
        """Obtiene la última fecha disponible."""
        return self.session.scalar(
            select(func.max(MarketHistoryModel.date)).where(
                MarketHistoryModel.symbol == symbol.strip().upper()
            )
        )

    def symbols(self) -> list[str]:
        """Lista símbolos con histórico local."""
        return list(
            self.session.scalars(
                select(MarketHistoryModel.symbol)
                .distinct()
                .order_by(MarketHistoryModel.symbol)
            )
        )

    def count(self) -> int:
        """Cuenta todas las velas almacenadas."""
        return int(
            self.session.scalar(select(func.count(MarketHistoryModel.id))) or 0
        )

    def save_sync(
        self,
        symbol: str,
        provider: str,
        status: str,
        rows_added: int,
        error_message: str | None = None,
    ) -> None:
        """Registra el resultado sin datos sensibles."""
        self.session.add(
            MarketSyncLogModel(
                symbol=symbol.strip().upper(),
                provider=provider,
                status=status,
                rows_added=rows_added,
                error_message=error_message[:500] if error_message else None,
            )
        )
        self.session.flush()

    def recent_errors(self, limit: int = 10) -> list[MarketSyncLogModel]:
        """Devuelve errores recientes."""
        statement = (
            select(MarketSyncLogModel)
            .where(MarketSyncLogModel.status == "ERROR")
            .order_by(MarketSyncLogModel.created_at.desc())
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def latest_sync(self) -> MarketSyncLogModel | None:
        """Devuelve la sincronización más reciente."""
        return self.session.scalar(
            select(MarketSyncLogModel)
            .order_by(MarketSyncLogModel.created_at.desc())
            .limit(1)
        )


class IndicatorCacheRepository:
    """Cache persistente de resultados técnicos."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, symbol: str) -> IndicatorCacheModel | None:
        return self.session.get(IndicatorCacheModel, symbol.strip().upper())

    def save(self, symbol: str, last_date: date, payload: str) -> None:
        normalized = symbol.strip().upper()
        item = self.get(normalized)
        if item is None:
            item = IndicatorCacheModel(
                symbol=normalized, last_history_date=last_date, payload=payload
            )
            self.session.add(item)
        else:
            item.last_history_date = last_date
            item.payload = payload
        self.session.flush()
