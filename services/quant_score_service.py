"""Contratos preparatorios para Quant Score; algoritmo reservado a Fase 4."""

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class QuantScoreInput(BaseModel):
    """Entrada futura basada en métricas ya calculadas."""

    symbol: str
    metrics: dict[str, float | None]


class QuantScoreResult(BaseModel):
    """Resultado estructural sin interpretación de inversión."""

    symbol: str
    score: float = Field(ge=0, le=100)
    components: dict[str, float]
    methodology_version: str


class QuantScoreService(ABC):
    """Interfaz que será implementada en una fase posterior."""

    @abstractmethod
    def evaluate(self, data: QuantScoreInput) -> QuantScoreResult:
        """Evalúa métricas cuando exista una metodología aprobada."""
        raise NotImplementedError("Quant Score pertenece a la Fase 4.")

