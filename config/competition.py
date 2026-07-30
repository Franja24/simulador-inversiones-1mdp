"""Configuración versionada de Competition Intelligence."""

from pydantic import BaseModel, Field, model_validator


class CompetitionConfig(BaseModel):
    model_version: str = "competition-1.0"
    top_n: int = Field(default=10, ge=1, le=50)
    lookback_sessions: int = Field(default=60, ge=20, le=252)
    transaction_cost_bps_per_side: float = Field(default=10, ge=0)
    minimum_rebalance_benefit_mxn: float = Field(default=500, ge=0)
    maximum_recommended_turnover: float = Field(default=0.35, ge=0, le=1)
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "monte_carlo": 0.20,
            "aqs": 0.25,
            "momentum": 0.15,
            "beating_benchmark": 0.20,
            "liquidity": 0.10,
            "risk": 0.10,
        }
    )
    liquidity_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "spread": 0.40,
            "volume": 0.35,
            "execution": 0.25,
        }
    )

    @model_validator(mode="after")
    def validate_weights(self) -> "CompetitionConfig":
        if set(self.weights) != {
            "monte_carlo",
            "aqs",
            "momentum",
            "beating_benchmark",
            "liquidity",
            "risk",
        }:
            raise ValueError("Los componentes del Competition Score son obligatorios.")
        if abs(sum(self.weights.values()) - 1) > 1e-9:
            raise ValueError("Los pesos del Competition Score deben sumar 1.")
        if abs(sum(self.liquidity_weights.values()) - 1) > 1e-9:
            raise ValueError("Los pesos de Liquidity Score deben sumar 1.")
        if any(value < 0 for value in [*self.weights.values(), *self.liquidity_weights.values()]):
            raise ValueError("Los pesos no pueden ser negativos.")
        return self
