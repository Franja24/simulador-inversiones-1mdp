"""Fachada de Fase 5; nunca ejecuta operaciones reales."""

import hashlib
from datetime import date

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config.simulation import MonteCarloConfig, PortfolioOptimizationConfig
from domain.simulation import (
    AssetSimulationResult,
    OptimizationResult,
    PortfolioSimulationResult,
    StressScenarioResult,
)
from repositories.simulation_repository import SimulationRepository
from services.monte_carlo_service import MonteCarloService
from services.portfolio_optimization_service import PortfolioOptimizationService
from services.stress_test_service import StressTestService


class SimulationInput(BaseModel):
    """DTO legado conservado para compatibilidad."""

    symbol: str
    horizon_days: int = Field(gt=0)
    paths: int = Field(gt=0)
    seed: int | None = None


class SimulationResult(BaseModel):
    """DTO legado conservado para compatibilidad."""

    symbol: str
    horizon_days: int
    paths: int
    percentiles: dict[str, float]
    methodology_version: str


class SimulationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.monte_carlo = MonteCarloService(session)
        self.optimizer = PortfolioOptimizationService(session)
        self.stress = StressTestService()
        self.repository = SimulationRepository(session)

    def simulate_symbol(
        self,
        symbol: str,
        effective_date: date,
        benchmark_symbol: str,
        config: MonteCarloConfig,
    ) -> AssetSimulationResult:
        result = self.monte_carlo.simulate_asset(
            symbol, effective_date, benchmark_symbol, config
        )
        self._save(
            result.model_dump(), result.data_signature, result.seed, portfolio=False
        )
        return result

    def simulate_portfolio(
        self,
        weights: dict[str, float],
        effective_date: date,
        benchmark_symbol: str,
        config: MonteCarloConfig,
        *,
        cash_weight: float | None = None,
        maximum_symbol_weight: float = 1,
        allow_cash: bool = True,
    ) -> PortfolioSimulationResult:
        result = self.monte_carlo.simulate_portfolio(
            weights,
            effective_date,
            benchmark_symbol,
            config,
            cash_weight=cash_weight,
            maximum_symbol_weight=maximum_symbol_weight,
            allow_cash=allow_cash,
        )
        self._save(
            result.model_dump(), result.data_signature, result.seed, portfolio=True
        )
        return result

    def compare_portfolios(
        self,
        portfolios: dict[str, dict[str, float]],
        effective_date: date,
        benchmark_symbol: str,
        config: MonteCarloConfig,
    ) -> dict[str, float]:
        return {
            name: self.simulate_portfolio(
                weights, effective_date, benchmark_symbol, config
            ).horizons[-1].median_return
            for name, weights in portfolios.items()
        }

    def stress_test(
        self, weights: dict[str, float], scenario: str
    ) -> StressScenarioResult:
        result = self.stress.run_predefined(weights, scenario)
        payload = result.model_dump()
        run_id = hashlib.sha256(f"{weights}|{scenario}".encode()).hexdigest()[:24]
        self.repository.save(run_id, payload, kind="stress")
        self.repository.save_stress_details(run_id, payload)
        self.session.commit()
        return result

    def optimize_portfolio(
        self,
        symbols: list[str],
        effective_date: date,
        benchmark_symbol: str,
        simulation_config: MonteCarloConfig,
        optimization_config: PortfolioOptimizationConfig,
    ) -> OptimizationResult:
        result = self.optimizer.optimize(
            symbols,
            effective_date,
            benchmark_symbol,
            simulation_config,
            optimization_config,
        )
        self.repository.save(result.run_id, result.model_dump(), kind="optimization")
        self.repository.save_optimization_details(result.run_id, result.model_dump())
        self.session.commit()
        return result

    def load_run(self, run_id: str) -> dict[str, object] | None:
        return self.repository.load(run_id)

    def reproduce_run(self, run_id: str) -> dict[str, object]:
        stored = self.load_run(run_id)
        if stored is None:
            raise ValueError("Ejecución no encontrada.")
        return stored

    def _save(
        self,
        payload: dict[str, object],
        signature: str,
        seed: int,
        *,
        portfolio: bool,
    ) -> None:
        run_id = hashlib.sha256(
            f"{signature}|{seed}|{payload}".encode()
        ).hexdigest()[:24]
        payload = {
            **payload,
            "run_id": run_id,
            "data_signature": signature,
            "seed": seed,
        }
        self.repository.save(run_id, payload, kind="simulation")
        self.repository.save_simulation_details(
            run_id, payload, portfolio=portfolio
        )
        self.session.commit()
