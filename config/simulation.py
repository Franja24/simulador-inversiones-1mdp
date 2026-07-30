"""Configuración versionada de simulación, reglas y optimización."""

from pydantic import BaseModel, Field, model_validator


class MonteCarloConfig(BaseModel):
    model_version: str = "mc-1.0"
    simulation_method: str = "correlated_bootstrap"
    horizons: list[int] = Field(default_factory=lambda: [5, 10, 15])
    simulation_count: int = Field(default=10_000, ge=100, le=100_000)
    lookback_sessions: int = Field(default=252, ge=20)
    block_size: int = Field(default=5, gt=0)
    random_seed: int = 42
    use_adjusted_close: bool = True
    preserve_correlation: bool = True
    regime_conditioning: bool = True
    regime_mode: str = "weighted_sampling"
    minimum_history_rows: int = Field(default=126, ge=2)
    winsor_lower: float = Field(default=0.01, ge=0, lt=0.5)
    winsor_upper: float = Field(default=0.99, gt=0.5, le=1)
    confidence_level: float = Field(default=0.95, gt=0, lt=1)
    risk_free_rate: float = 0.0
    transaction_cost_bps_per_side: float = Field(default=10, ge=0)
    slippage_bps_per_side: float = Field(default=0, ge=0)
    maximum_missing_ratio: float = Field(default=0.05, ge=0, le=1)
    minimum_confidence: float = Field(default=50, ge=0, le=100)
    return_type: str = "simple"
    student_t_degrees_freedom: float = Field(default=5, gt=2)
    sample_path_count: int = Field(default=25, ge=0, le=500)

    @model_validator(mode="after")
    def validate_config(self) -> "MonteCarloConfig":
        allowed = {
            "independent_bootstrap", "correlated_bootstrap", "block_bootstrap",
            "parametric_normal", "parametric_student_t",
        }
        if self.simulation_method not in allowed:
            raise ValueError("Método Monte Carlo inválido.")
        if not self.horizons or any(item <= 0 for item in self.horizons):
            raise ValueError("Los horizontes deben ser positivos.")
        if self.block_size >= self.lookback_sessions:
            raise ValueError("block_size debe ser menor que lookback_sessions.")
        if self.winsor_lower >= self.winsor_upper:
            raise ValueError("Percentiles de winsorización inválidos.")
        if self.return_type not in {"simple", "log"}:
            raise ValueError("Tipo de retorno inválido.")
        if self.regime_mode not in {
            "hard_filter", "weighted_sampling", "recency_weighted"
        }:
            raise ValueError("Modo de régimen inválido.")
        return self


class ChallengeRulesConfig(BaseModel):
    minimum_symbols: int = Field(default=1, gt=0)
    maximum_symbols: int = Field(default=10, gt=0)
    maximum_symbol_weight: float = Field(default=0.50, gt=0, le=1)
    allow_cash: bool = True
    maximum_cash_weight: float = Field(default=0.20, ge=0, le=1)
    leverage_allowed: bool = False
    allowed_symbols: list[str] = Field(default_factory=list)
    excluded_symbols: list[str] = Field(default_factory=list)
    minimum_liquidity: float | None = Field(default=None, ge=0)
    minimum_confidence: float = Field(default=0, ge=0, le=100)


class PortfolioOptimizationConfig(BaseModel):
    method: str = "monte_carlo_search"
    candidate_count: int = Field(default=5_000, ge=10, le=50_000)
    objective: str = "robust_competition_score"
    horizon_sessions: int = Field(default=15, gt=0)
    minimum_symbols: int = Field(default=5, gt=0)
    maximum_symbols: int = Field(default=10, gt=0)
    maximum_symbol_weight: float = Field(default=0.50, gt=0, le=1)
    minimum_symbol_weight: float = Field(default=0.02, ge=0, le=1)
    allow_cash: bool = True
    maximum_cash_weight: float = Field(default=0.20, ge=0, le=1)
    minimum_confidence: float = Field(default=50, ge=0, le=100)
    minimum_aqs: float | None = Field(default=None, ge=0, le=100)
    maximum_expected_shortfall: float | None = None
    maximum_var: float | None = None
    minimum_probability_positive: float | None = Field(default=None, ge=0, le=1)
    minimum_probability_beating_benchmark: float | None = Field(
        default=None, ge=0, le=1
    )
    maximum_concentration: float | None = Field(default=None, gt=0, le=1)
    minimum_liquidity: float | None = Field(default=None, ge=0)
    excluded_symbols: list[str] = Field(default_factory=list)
    diversification_penalty: float = Field(default=0, ge=0)
    concentration_penalty: float = Field(default=0, ge=0)
    turnover_penalty: float = Field(default=0, ge=0)
    random_seed: int = 42
    robust_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "probability_beating_benchmark": 0.30,
            "probability_positive": 0.20,
            "p75": 0.20,
            "median": 0.15,
            "expected_shortfall": 0.10,
            "diversification": 0.05,
        }
    )

    @model_validator(mode="after")
    def validate_optimizer(self) -> "PortfolioOptimizationConfig":
        objectives = {
            "expected_return", "median_return", "probability_positive",
            "probability_beating_benchmark", "return_to_expected_shortfall",
            "return_to_var", "aqs_weighted_probability",
            "robust_competition_score",
        }
        if self.objective not in objectives:
            raise ValueError("Objetivo de optimización inválido.")
        if abs(sum(self.robust_weights.values()) - 1) > 1e-9:
            raise ValueError("Los pesos del Robust Competition Score deben sumar 1.")
        if self.minimum_symbols > self.maximum_symbols:
            raise ValueError("minimum_symbols no puede exceder maximum_symbols.")
        return self
