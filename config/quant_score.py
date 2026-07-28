"""Configuración versionada y visible del Actinver Quant Score."""

from math import isclose

from pydantic import BaseModel, Field, model_validator


class QuantScoreConfig(BaseModel):
    model_version: str = "aqs-1.0"
    momentum_20_weight: float = Field(default=0.25, ge=0)
    momentum_10_weight: float = Field(default=0.15, ge=0)
    momentum_5_weight: float = Field(default=0.10, ge=0)
    relative_strength_weight: float = Field(default=0.15, ge=0)
    trend_weight: float = Field(default=0.10, ge=0)
    volume_weight: float = Field(default=0.10, ge=0)
    volatility_weight: float = Field(default=0.10, ge=0)
    distance_to_high_weight: float = Field(default=0.05, ge=0)
    minimum_history_rows: int = Field(default=60, ge=20)
    minimum_liquidity: float | None = Field(default=None, ge=0)
    normalization_method: str = "percentile_rank"
    winsor_lower: float = Field(default=0.05, ge=0, lt=0.5)
    winsor_upper: float = Field(default=0.95, gt=0.5, le=1)
    risk_penalty_intensity: float = Field(default=0.50, ge=0, le=1)
    regime_adjustment_enabled: bool = True
    maximum_regime_adjustment: float = Field(default=10, ge=0, le=10)
    high_volatility_confidence_penalty: float = Field(default=10, ge=0, le=50)
    extreme_extension_threshold: float = Field(default=0.03, ge=0)

    @model_validator(mode="after")
    def validate_configuration(self) -> "QuantScoreConfig":
        if self.normalization_method not in {"percentile_rank", "robust_zscore"}:
            raise ValueError("Método de normalización inválido.")
        if self.winsor_lower >= self.winsor_upper:
            raise ValueError("Los percentiles de winsorización están invertidos.")
        if not isclose(sum(self.weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError("Los pesos AQS deben sumar exactamente 1.0.")
        return self

    @property
    def weights(self) -> dict[str, float]:
        return {
            "momentum_20": self.momentum_20_weight,
            "momentum_10": self.momentum_10_weight,
            "momentum_5": self.momentum_5_weight,
            "relative_strength": self.relative_strength_weight,
            "trend": self.trend_weight,
            "volume": self.volume_weight,
            "volatility": self.volatility_weight,
            "distance_to_high": self.distance_to_high_weight,
        }


class BacktestConfig(BaseModel):
    top_n: int = Field(default=5, gt=0)
    rebalance_frequency: int = Field(default=5, gt=0)
    holding_period: int = Field(default=5, gt=0)
    weighting: str = "equal_weight"
    transaction_cost_bps: float = Field(default=10, ge=0)
    allow_cash: bool = True
    maximum_symbol_weight: float = Field(default=0.25, gt=0, le=1)
    minimum_confidence: float = Field(default=0, ge=0, le=100)
    random_seed: int = 42
    calibration_sessions: int = Field(default=252, ge=20)
    evaluation_sessions: int = Field(default=20, gt=0)

    @model_validator(mode="after")
    def validate_weighting(self) -> "BacktestConfig":
        if self.weighting != "equal_weight":
            raise ValueError("La primera versión solo admite equal_weight.")
        if self.rebalance_frequency < self.holding_period:
            raise ValueError(
                "Esta versión no admite posiciones solapadas; la frecuencia de "
                "rebalanceo debe ser mayor o igual al periodo de mantenimiento."
            )
        if not self.allow_cash and self.top_n * self.maximum_symbol_weight < 1:
            raise ValueError(
                "No es posible asignar 100%: top_n × maximum_symbol_weight < 1."
            )
        return self
