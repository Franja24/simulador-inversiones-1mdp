"""DTOs transparentes para AQS, régimen y backtesting."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ScoreComponent(BaseModel):
    name: str
    raw_value: float | None
    normalized_score: float = Field(ge=0, le=100)
    weight: float = Field(ge=0, le=1)
    weighted_score: float = Field(ge=0, le=100)
    explanation: str
    data_available: bool


class MarketRegimeResult(BaseModel):
    effective_date: date
    benchmark_symbol: str
    primary_regime: Literal[
        "BULLISH", "BEARISH", "SIDEWAYS", "INSUFFICIENT_DATA"
    ]
    high_volatility: bool
    confidence: float = Field(ge=0, le=100)
    metrics: dict[str, float | None]
    warnings: list[str] = Field(default_factory=list)


class QuantScoreResult(BaseModel):
    symbol: str
    effective_date: date
    base_score: float = Field(ge=0, le=100)
    regime_adjustment: float = Field(ge=-10, le=10)
    total_score: float = Field(ge=0, le=100)
    classification: str
    confidence: float = Field(ge=0, le=100)
    components: list[ScoreComponent]
    warnings: list[str]
    model_version: str
    benchmark_symbol: str
    market_regime: str


class RankingEntry(BaseModel):
    rank: int = Field(gt=0)
    symbol: str
    score: float = Field(ge=0, le=100)
    base_score: float = Field(ge=0, le=100)
    regime_adjustment: float
    classification: str
    confidence: float = Field(ge=0, le=100)
    daily_return: float | None
    weekly_return: float | None
    monthly_return: float | None
    relative_strength: float | None
    volatility: float | None
    relative_volume: float | None
    warnings: list[str]
    score_change: float | None = None
    rank_change: int | None = None
    classification_change: str | None = None


class BacktestTrade(BaseModel):
    signal_date: date
    execution_date: date
    exit_date: date
    symbol: str
    entry_price: float
    exit_price: float
    gross_return: float
    net_return: float
    weight: float
    transaction_cost: float


class BacktestMetrics(BaseModel):
    cumulative_return: float
    annualized_return: float | None
    volatility: float
    sharpe: float | None
    sortino: float | None
    max_drawdown: float
    hit_rate: float
    average_trade: float
    profit_factor: float | None
    turnover: float
    benchmark_return: float | None
    relative_return: float | None
    information_ratio: float | None
    benchmark_win_rate: float | None


class BacktestResult(BaseModel):
    run_id: str
    generated_at: datetime
    model_version: str
    start_date: date
    end_date: date
    benchmark_symbol: str
    equity_curve: list[dict[str, float | str]]
    benchmark_curve: list[dict[str, float | str]]
    trades: list[BacktestTrade]
    metrics: BacktestMetrics
    comparison: dict[str, float]
    walk_forward_periods: list[dict[str, str | float]]
    warnings: list[str]
    configuration: dict[str, object]

