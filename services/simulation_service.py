"""Tipos preparatorios para simulaciones; sin Monte Carlo en Fase 3."""

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class SimulationInput(BaseModel):
    """Parámetros que una simulación futura podrá consumir."""

    symbol: str
    horizon_days: int = Field(gt=0)
    paths: int = Field(gt=0)
    seed: int | None = None


class SimulationResult(BaseModel):
    """Contenedor neutral para resultados futuros."""

    symbol: str
    horizon_days: int
    paths: int
    percentiles: dict[str, float]
    methodology_version: str


class SimulationService(ABC):
    """Interfaz reservada para una implementación posterior."""

    @abstractmethod
    def run(self, data: SimulationInput) -> SimulationResult:
        """Ejecuta una simulación cuando se habilite en Fase 4."""
        raise NotImplementedError("Monte Carlo pertenece a la Fase 4.")
