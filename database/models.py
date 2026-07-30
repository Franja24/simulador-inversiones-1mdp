"""Entidades persistentes de la Fase 1."""

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
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
    history_row_count: Mapped[int] = mapped_column(Integer, default=0)
    history_version: Mapped[str] = mapped_column(String(64), default="")
    indicator_version: Mapped[str] = mapped_column(String(20), default="1")
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


class MarketDateStatusModel(Base):
    """Fecha consultada sin datos o confirmada como no operativa."""

    __tablename__ = "market_date_status"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "date", "provider", name="uq_market_date_status_symbol_date"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(30))
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class QuantUniverseModel(Base):
    """Emisora habilitada explícitamente para análisis cuantitativo."""

    __tablename__ = "quant_universe"
    symbol: Mapped[str] = mapped_column(String(30), primary_key=True)
    company_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    active: Mapped[bool] = mapped_column(default=True, index=True)
    minimum_liquidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class QuantScoreConfigModel(Base):
    """Instantánea inmutable de una configuración versionada."""

    __tablename__ = "quant_score_configs"
    model_version: Mapped[str] = mapped_column(String(40), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class QuantScoreRunModel(Base):
    """Ejecución reproducible del AQS para un universo y una fecha."""

    __tablename__ = "quant_score_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    effective_date: Mapped[date] = mapped_column(Date, index=True)
    model_version: Mapped[str] = mapped_column(String(40), index=True)
    benchmark_symbol: Mapped[str] = mapped_column(String(30))
    universe_json: Mapped[str] = mapped_column(Text)
    config_json: Mapped[str] = mapped_column(Text)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class QuantScoreResultModel(Base):
    """Resultado final versionado por símbolo y fecha."""

    __tablename__ = "quant_score_results"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "effective_date",
            "model_version",
            name="uq_quant_score_symbol_date_version",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("quant_score_runs.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    effective_date: Mapped[date] = mapped_column(Date, index=True)
    model_version: Mapped[str] = mapped_column(String(40), index=True)
    benchmark_symbol: Mapped[str] = mapped_column(String(30))
    market_regime: Mapped[str] = mapped_column(String(30))
    base_score: Mapped[float] = mapped_column(Float)
    regime_adjustment: Mapped[float] = mapped_column(Float)
    total_score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    classification: Mapped[str] = mapped_column(String(30))
    data_status: Mapped[str] = mapped_column(String(30), default="OK")
    warnings_json: Mapped[str] = mapped_column(Text)
    diagnostics_json: Mapped[str] = mapped_column(Text)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class QuantScoreComponentModel(Base):
    """Desglose auditable de factores que forman un score."""

    __tablename__ = "quant_score_components"
    __table_args__ = (
        UniqueConstraint("result_id", "name", name="uq_quant_component_result_name"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    result_id: Mapped[int] = mapped_column(
        ForeignKey("quant_score_results.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(50))
    raw_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalized_score: Mapped[float] = mapped_column(Float)
    weight: Mapped[float] = mapped_column(Float)
    weighted_score: Mapped[float] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text)
    data_available: Mapped[bool] = mapped_column(default=True)


class MarketRegimeSnapshotModel(Base):
    """Régimen único del benchmark calculado sin información futura."""

    __tablename__ = "market_regime_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "benchmark_symbol",
            "effective_date",
            "model_version",
            name="uq_regime_benchmark_date_version",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    benchmark_symbol: Mapped[str] = mapped_column(String(30), index=True)
    effective_date: Mapped[date] = mapped_column(Date, index=True)
    model_version: Mapped[str] = mapped_column(String(40))
    primary_regime: Mapped[str] = mapped_column(String(30))
    high_volatility: Mapped[bool] = mapped_column(default=False)
    confidence: Mapped[float] = mapped_column(Float)
    metrics_json: Mapped[str] = mapped_column(Text)
    warnings_json: Mapped[str] = mapped_column(Text)


class BacktestRunModel(Base):
    """Backtest reproducible con configuración y resultado serializados."""

    __tablename__ = "backtest_runs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_version: Mapped[str] = mapped_column(String(40), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    benchmark_symbol: Mapped[str] = mapped_column(String(30))
    config_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WalkForwardRunModel(Base):
    """Validación OOS agregada y reproducible."""

    __tablename__ = "walk_forward_runs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_version: Mapped[str] = mapped_column(String(40), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    benchmark_symbol: Mapped[str] = mapped_column(String(30))
    audit_json: Mapped[str] = mapped_column(Text)
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CompetitionSnapshotModel(Base):
    """Snapshot diario reproducible del asistente de competencia."""

    __tablename__ = "competition_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id",
            "effective_date",
            "model_version",
            name="uq_competition_portfolio_date_version",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id"), index=True
    )
    effective_date: Mapped[date] = mapped_column(Date, index=True)
    model_version: Mapped[str] = mapped_column(String(40), index=True)
    benchmark_symbol: Mapped[str] = mapped_column(String(30))
    competition_scores_json: Mapped[str] = mapped_column(Text)
    top_candidates_json: Mapped[str] = mapped_column(Text)
    recommended_portfolio_json: Mapped[str] = mapped_column(Text)
    risk_json: Mapped[str] = mapped_column(Text)
    rebalance_json: Mapped[str] = mapped_column(Text)
    dashboard_json: Mapped[str] = mapped_column(Text)
    data_signature: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


def _phase5_table(name: str) -> Table:
    return Table(
        name,
        Base.metadata,
        Column("id", Integer, primary_key=True),
        Column("run_id", String(64), index=True),
        Column("model_version", String(40), index=True),
        Column("effective_date", Date, nullable=True),
        Column("data_signature", String(64), nullable=True),
        Column("seed", Integer, nullable=True),
        Column("status", String(30), default="OK"),
        Column("payload", Text, nullable=False),
        Column("created_at", DateTime(timezone=True), default=utc_now),
    )


monte_carlo_runs = _phase5_table("monte_carlo_runs")
asset_simulation_results = _phase5_table("asset_simulation_results")
portfolio_simulation_results = _phase5_table("portfolio_simulation_results")
simulation_horizon_results = _phase5_table("simulation_horizon_results")
optimization_runs = _phase5_table("optimization_runs")
optimization_candidates = _phase5_table("optimization_candidates")
candidate_weights = _phase5_table("candidate_weights")
stress_test_runs = _phase5_table("stress_test_runs")
stress_test_results = _phase5_table("stress_test_results")
robustness_results = _phase5_table("robustness_results")
