"""Entidades persistentes de la Fase 1."""

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.connection import Base


def utc_now() -> datetime:
    """Genera una marca de tiempo UTC."""
    return datetime.now(UTC)


class TransactionType(StrEnum):
    """Tipos permitidos de operación."""

    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    COMMISSION = "COMMISSION"
    ADJUSTMENT = "ADJUSTMENT"


class PortfolioModel(Base):
    """Portafolio persistente."""

    __tablename__ = "portfolios"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    initial_capital: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    available_cash: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    current_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    challenge_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    challenge_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    benchmark_symbol: Mapped[str] = mapped_column(String(30), default="^MXX")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    transactions: Mapped[list["TransactionModel"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )


class TransactionModel(Base):
    """Operación inmutable registrada en el portafolio."""

    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), index=True)
    transaction_type: Mapped[TransactionType] = mapped_column(SqlEnum(TransactionType))
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    company_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=0)
    commission: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    taxes: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    transaction_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    strategy: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    portfolio: Mapped[PortfolioModel] = relationship(back_populates="transactions")


class AuditLogModel(Base):
    """Rastro de acciones relevantes."""

    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ManualPriceModel(Base):
    """Precio capturado manualmente con historial completo."""

    __tablename__ = "manual_prices"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    price_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="manual")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class MarketHistoryModel(Base):
    """Vela diaria persistente obtenida de un proveedor de mercado."""

    __tablename__ = "market_history"
    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_market_history_symbol_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    adj_close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer)
    dividends: Mapped[float] = mapped_column(Float, default=0)
    stock_splits: Mapped[float] = mapped_column(Float, default=0)
    timezone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class IndicatorCacheModel(Base):
    """Cache serializado de indicadores ligado a la última vela."""

    __tablename__ = "indicator_cache"
    symbol: Mapped[str] = mapped_column(String(30), primary_key=True)
    last_history_date: Mapped[date] = mapped_column(Date)
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class MarketSyncLogModel(Base):
    """Resultado compacto de una sincronización de mercado."""

    __tablename__ = "market_sync_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), index=True)
    rows_added: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
