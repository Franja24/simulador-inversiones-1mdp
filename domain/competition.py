"""DTOs explicables de Competition Intelligence."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class LiquidityScore(BaseModel):
    symbol: str
    score: float = Field(ge=0, le=100)
    estimated_spread: float = Field(ge=0)
    average_volume: float = Field(ge=0)
    execution_ease: float = Field(ge=0, le=100)
    components: dict[str, float]


class CompetitionCandidate(BaseModel):
    symbol: str
    rank: int = 0
    competition_score: float = Field(ge=0, le=100)
    aqs: float = Field(ge=0, le=100)
    monte_carlo: float = Field(ge=0, le=100)
    momentum: float = Field(ge=0, le=100)
    probability_beating_benchmark: float = Field(ge=0, le=1)
    liquidity: LiquidityScore
    risk_penalty: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=100)
    expected_return: float
    expected_shortfall: float = Field(ge=0)
    expected_drawdown: float = Field(ge=0)
    market_regime: str
    main_reason: str
    explanation: dict[str, str]


class RebalanceAdvice(BaseModel):
    current_weights: dict[str, float]
    optimal_weights: dict[str, float]
    purchases: dict[str, float]
    sales: dict[str, float]
    expected_cost: float = Field(ge=0)
    expected_benefit: float
    turnover: float = Field(ge=0)
    recommend: bool
    recommendation: str
    justification: str


class CompetitionDashboard(BaseModel):
    portfolio_id: int
    effective_date: date
    generated_at: datetime
    capital_initial: float
    portfolio_value: float
    buying_power: float
    benchmark_symbol: str
    benchmark_return: float
    portfolio_return: float
    excess_return: float
    market_regime: str
    confidence: float = Field(ge=0, le=100)
    risk_level: str
    model_status: str
    last_update: date | None
    top_candidates: list[CompetitionCandidate]
    recommended_portfolio: dict[str, float]
    rebalance: RebalanceAdvice
    warnings: list[str] = Field(default_factory=list)


class DailyBrief(BaseModel):
    effective_date: date
    market: str
    regime: str
    confidence: float
    top_candidates: list[str]
    risk: str
    rebalance_recommended: bool
    recommendation: str
    justification: str
    markdown: str
