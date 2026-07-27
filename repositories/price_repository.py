"""Repositorios de precios, con compatibilidad para el almacén en memoria."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import ManualPriceModel


class PriceSource(Protocol):
    """Interfaz mínima consumida por la valoración."""

    def get(self, symbol: str) -> Decimal | None:
        """Obtiene el precio más reciente."""
        ...

    def get_last_update_time(self, symbol: str) -> datetime | None:
        """Obtiene la fecha del precio más reciente."""
        ...


class PriceRepository:
    """Almacén en memoria conservado para compatibilidad con Fase 1."""

    def __init__(self, prices: dict[str, Decimal] | None = None) -> None:
        self._prices = {symbol.upper(): price for symbol, price in (prices or {}).items()}

    def set(self, symbol: str, price: Decimal) -> None:
        """Registra un precio positivo."""
        if price <= 0:
            raise ValueError("El precio debe ser mayor que cero.")
        self._prices[symbol.strip().upper()] = price

    def get(self, symbol: str) -> Decimal | None:
        """Obtiene un precio, si existe."""
        return self._prices.get(symbol.strip().upper())

    def get_last_update_time(self, symbol: str) -> datetime | None:
        """El almacén legado no conserva fechas."""
        return None


class SqlPriceRepository:
    """Persiste y recupera el historial de precios manuales."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, price: ManualPriceModel) -> ManualPriceModel:
        """Agrega un precio al historial."""
        self.session.add(price)
        self.session.flush()
        return price

    def latest(self, symbol: str) -> ManualPriceModel | None:
        """Devuelve el registro más reciente por fecha e identificador."""
        statement = (
            select(ManualPriceModel)
            .where(ManualPriceModel.symbol == symbol.strip().upper())
            .order_by(ManualPriceModel.price_date.desc(), ManualPriceModel.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def get(self, symbol: str) -> Decimal | None:
        """Devuelve únicamente el valor más reciente."""
        record = self.latest(symbol)
        return record.price if record else None

    def get_last_update_time(self, symbol: str) -> datetime | None:
        """Devuelve la fecha del valor más reciente."""
        record = self.latest(symbol)
        if record is None:
            return None
        if record.price_date.tzinfo is None:
            return record.price_date.replace(tzinfo=UTC)
        return record.price_date

    def list_all(self, symbol: str | None = None) -> list[ManualPriceModel]:
        """Lista el historial, opcionalmente filtrado por emisora."""
        statement = select(ManualPriceModel)
        if symbol:
            statement = statement.where(
                ManualPriceModel.symbol == symbol.strip().upper()
            )
        statement = statement.order_by(
            ManualPriceModel.price_date.desc(), ManualPriceModel.id.desc()
        )
        return list(self.session.scalars(statement))
