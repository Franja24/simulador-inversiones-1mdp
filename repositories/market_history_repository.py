"""Persistencia de históricos, indicadores y sincronizaciones."""

import hashlib
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.models import (
    IndicatorCacheModel,
    MarketDateStatusModel,
    MarketHistoryModel,
    MarketSyncLogModel,
)
from domain.market import MarketBar


class MarketHistoryRepository:
    """Repositorio de velas diarias sin dependencia del proveedor externo."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, bars: list[MarketBar]) -> int:
        """Inserta o corrige velas válidas y devuelve filas modificadas."""
        if not bars:
            return 0
        validated = [MarketBar.model_validate(bar.model_dump()) for bar in bars]
        symbol = validated[0].symbol
        unique = {
            bar.date: bar for bar in validated if bar.symbol == symbol
        }
        existing = {
            item.date: item
            for item in self.session.scalars(
                select(MarketHistoryModel).where(
                    MarketHistoryModel.symbol == symbol,
                    MarketHistoryModel.date.in_(set(unique)),
                )
            )
        }
        changed = 0
        for bar_date, bar in unique.items():
            item = existing.get(bar_date)
            if item is None:
                self.session.add(
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
                )
                changed += 1
                continue
            values = (
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.adj_close,
                bar.volume,
                bar.dividends,
                bar.stock_splits,
                bar.timezone,
                bar.provider,
            )
            current = (
                item.open,
                item.high,
                item.low,
                item.close,
                item.adj_close,
                item.volume,
                item.dividends,
                item.stock_splits,
                item.timezone,
                item.provider,
            )
            if values != current:
                (
                    item.open,
                    item.high,
                    item.low,
                    item.close,
                    item.adj_close,
                    item.volume,
                    item.dividends,
                    item.stock_splits,
                    item.timezone,
                    item.provider,
                ) = values
                changed += 1
        self.session.flush()
        return changed

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

    def history_signature(self, symbol: str) -> tuple[date | None, int, str]:
        """Calcula una huella determinista de valores relevantes."""
        rows = self.list_history(symbol)
        if not rows:
            return None, 0, ""
        digest = hashlib.sha256()
        for item in rows:
            digest.update(
                "|".join(
                    [
                        item.date.isoformat(),
                        repr(item.open),
                        repr(item.high),
                        repr(item.low),
                        repr(item.close),
                        repr(item.adj_close),
                        str(item.volume),
                        repr(item.dividends),
                        repr(item.stock_splits),
                    ]
                ).encode()
            )
        return rows[-1].date, len(rows), digest.hexdigest()

    def known_no_data(
        self, symbol: str, provider: str, start: date, end: date
    ) -> set[date]:
        """Devuelve fechas previamente confirmadas sin datos."""
        statement = select(MarketDateStatusModel.date).where(
            MarketDateStatusModel.symbol == symbol.strip().upper(),
            MarketDateStatusModel.provider == provider,
            MarketDateStatusModel.date >= start,
            MarketDateStatusModel.date <= end,
            MarketDateStatusModel.status.in_(("NO_DATA", "NON_TRADING_DAY")),
        )
        return set(self.session.scalars(statement))

    def mark_date_status(
        self, symbol: str, provider: str, dates: set[date], status: str
    ) -> None:
        """Registra fechas no operativas sin crear duplicados."""
        if not dates:
            return
        existing = self.known_no_data(
            symbol, provider, min(dates), max(dates)
        )
        self.session.add_all(
            [
                MarketDateStatusModel(
                    symbol=symbol.strip().upper(),
                    date=item,
                    provider=provider,
                    status=status,
                )
                for item in dates - existing
            ]
        )
        self.session.flush()

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

    def save(
        self,
        symbol: str,
        last_date: date,
        row_count: int,
        history_version: str,
        indicator_version: str,
        payload: str,
    ) -> None:
        normalized = symbol.strip().upper()
        item = self.get(normalized)
        if item is None:
            item = IndicatorCacheModel(
                symbol=normalized,
                last_history_date=last_date,
                history_row_count=row_count,
                history_version=history_version,
                indicator_version=indicator_version,
                payload=payload,
            )
            self.session.add(item)
        else:
            item.last_history_date = last_date
            item.history_row_count = row_count
            item.history_version = history_version
            item.indicator_version = indicator_version
            item.payload = payload
        self.session.flush()
