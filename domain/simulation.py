"""DTOs de escenarios probabilísticos, riesgo y optimización."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class SimulationPercentiles(BaseModel):
    p01: float
    p05: float
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    p95: float
    p99: float


class HorizonSimulationResult(BaseModel):
    horizon_sessions: int
    simulation_count: int
    expected_return: float
    median_return: float
    standard_deviation: float
    probability_positive: float = Field(ge=0, le=1)
    probability_above_target: dict[str, float]
    probability_below_loss: dict[str, float]
    probability_beating_benchmark: float | None
    value_at_risk: float
    expected_shortfall: float
    value_at_risk_levels: dict[str, float]
    expected_shortfall_levels: dict[str, float]
    best_simulated_return: float
    worst_simulated_return: float
    expected_drawdown: float
    drawdown_p95: float
    probability_drawdown: dict[str, float]
    percentiles: SimulationPercentiles


class AssetSimulationResult(BaseModel):
    symbol: str
    effective_date: date
    method: str
    actual_method: str
    model_version: str
    regime: str
    confidence: float = Field(ge=0, le=100)
    horizons: list[HorizonSimulationResult]
    assumptions: list[str]
    warnings: list[str]
    data_signature: str
    seed: int
    configuration: dict[str, object] = Field(default_factory=dict)
    universe: list[str] = Field(default_factory=list)
    restrictions: dict[str, object] = Field(default_factory=dict)
    sample_paths: dict[str, list[list[float]]] = Field(default_factory=dict)


class PortfolioSimulationResult(BaseModel):
    symbols: list[str]
    weights: dict[str, float]
    cash_weight: float
    effective_date: date
    method: str
    actual_method: str
    model_version: str
    regime: str
    confidence: float = Field(ge=0, le=100)
    horizons: list[HorizonSimulationResult]
    diversification_ratio: float | None
    concentration: float
    expected_drawdown: float
    initial_rules_compliant: bool
    risk_contributions: dict[str, float]
    assumptions: list[str]
    warnings: list[str]
    data_signature: str
    seed: int
    configuration: dict[str, object] = Field(default_factory=dict)
    universe: list[str] = Field(default_factory=list)
    restrictions: dict[str, object] = Field(default_factory=dict)
    sample_paths: dict[str, list[list[float]]] = Field(default_factory=dict)


class StressScenarioResult(BaseModel):
    name: str
    asset_impacts: dict[str, float]
    portfolio_impact: float
    total_loss: float
    new_concentration: float
    damage_contribution: dict[str, float]
    rule_violations: list[str]
    warnings: list[str]


class OptimizationCandidate(BaseModel):
    candidate_id: str
    rank: int = 0
    weights: dict[str, float]
    cash_weight: float
    objective_score: float
    objective_requested: str = "robust_competition_score"
    objective_used: str = "robust_competition_score"
    raw_objective_score: float = 0
    penalties: dict[str, float] = Field(default_factory=dict)
    expected_return: float
    median_return: float
    probability_positive: float
    probability_beating_benchmark: float
    value_at_risk: float
    expected_shortfall: float
    expected_drawdown: float
    drawdown_p95: float = 0
    concentration: float
    weighted_aqs: float | None = None
    stability_score: float = 0
    fragile: bool = False
    warnings: list[str] = Field(default_factory=list)


class RejectedCandidate(BaseModel):
    candidate_id: str
    weights: dict[str, float]
    reasons: list[str]
    metrics: dict[str, float]


class OptimizationResult(BaseModel):
    run_id: str
    generated_at: datetime
    effective_date: date
    objective: str
    candidates: list[OptimizationCandidate]
    rejected_candidates: list[RejectedCandidate] = Field(default_factory=list)
    requested_objective: str = "robust_competition_score"
    used_objective: str = "robust_competition_score"
    configuration: dict[str, object]
    data_signature: str
    warnings: list[str]


class RobustnessResult(BaseModel):
    candidate_id: str
    seed_results: list[float]
    lookback_results: list[float]
    method_results: list[float]
    stress_results: list[float]
    stability_score: float
    fragile: bool
    warnings: list[str]
