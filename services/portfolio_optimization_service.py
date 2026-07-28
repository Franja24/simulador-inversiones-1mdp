"""Búsqueda vectorizada de candidatos restringidos sobre trayectorias comunes."""

import hashlib
from datetime import UTC, date, datetime
from typing import cast

import numpy as np
from sqlalchemy.orm import Session

from config.simulation import MonteCarloConfig, PortfolioOptimizationConfig
from domain.simulation import OptimizationCandidate, OptimizationResult, RobustnessResult
from services.monte_carlo_service import MonteCarloService


class PortfolioOptimizationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.monte_carlo = MonteCarloService(session)

    def generate_candidates(
        self,
        symbols: list[str],
        config: PortfolioOptimizationConfig,
    ) -> np.ndarray:
        count = len(symbols)
        if count < config.minimum_symbols:
            raise ValueError("El universo no cumple el mínimo de emisoras.")
        rng = np.random.default_rng(config.random_seed)
        raw = rng.dirichlet(np.ones(count), size=config.candidate_count)
        cash = (
            rng.uniform(0, config.maximum_cash_weight, size=(config.candidate_count, 1))
            if config.allow_cash
            else np.zeros((config.candidate_count, 1))
        )
        weights = raw * (1 - cash)
        valid = (
            (weights.max(axis=1) <= config.maximum_symbol_weight)
            & ((weights == 0) | (weights >= config.minimum_symbol_weight)).all(axis=1)
        )
        candidates = weights[valid]
        if not len(candidates):
            equal = np.full((1, count), 1 / count)
            if equal.max() > config.maximum_symbol_weight:
                raise ValueError("No fue posible generar candidatos válidos.")
            candidates = equal
        return cast(np.ndarray, candidates)

    def optimize(
        self,
        symbols: list[str],
        effective_date: date,
        benchmark_symbol: str,
        simulation_config: MonteCarloConfig,
        optimization_config: PortfolioOptimizationConfig,
        *,
        top_n: int = 20,
    ) -> OptimizationResult:
        universe = sorted(dict.fromkeys(item.upper() for item in symbols))
        matrix = self.monte_carlo._matrix(
            [*universe, benchmark_symbol.upper()], effective_date, simulation_config
        )
        self.monte_carlo.returns.validate_history(
            matrix,
            minimum_rows=simulation_config.minimum_history_rows,
            maximum_missing_ratio=simulation_config.maximum_missing_ratio,
        )
        candidates = self.generate_candidates(universe, optimization_config)
        cube, _, warnings = self.monte_carlo._simulate_cube(
            matrix, optimization_config.horizon_sessions, simulation_config
        )
        asset_terminal = np.prod(1 + cube[:, :, :-1], axis=1) - 1
        benchmark_terminal = np.prod(1 + cube[:, :, -1], axis=1) - 1
        portfolio_terminal = asset_terminal @ candidates.T
        median = np.median(portfolio_terminal, axis=0)
        expected = portfolio_terminal.mean(axis=0)
        positive = (portfolio_terminal > 0).mean(axis=0)
        beating = (portfolio_terminal > benchmark_terminal[:, None]).mean(axis=0)
        p75 = np.percentile(portfolio_terminal, 75, axis=0)
        p05 = np.percentile(portfolio_terminal, 5, axis=0)
        var = np.maximum(0, -p05)
        es = np.array(
            [
                max(0, -portfolio_terminal[:, index][
                    portfolio_terminal[:, index] <= p05[index]
                ].mean())
                for index in range(candidates.shape[0])
            ]
        )
        concentration = (candidates**2).sum(axis=1)
        diversification = 1 - concentration
        robust = (
            optimization_config.robust_weights["probability_beating_benchmark"] * beating
            + optimization_config.robust_weights["probability_positive"] * positive
            + optimization_config.robust_weights["p75"] * self._scale(p75)
            + optimization_config.robust_weights["median"] * self._scale(median)
            + optimization_config.robust_weights["expected_shortfall"] * (1 - self._scale(es))
            + optimization_config.robust_weights["diversification"] * diversification
            - optimization_config.concentration_penalty * concentration
        )
        order = np.argsort(-robust)[:top_n]
        output = [
            OptimizationCandidate(
                candidate_id=hashlib.sha256(candidates[index].tobytes()).hexdigest()[:16],
                rank=rank,
                weights={
                    symbol: float(value)
                    for symbol, value in zip(universe, candidates[index], strict=True)
                    if value > 0
                },
                cash_weight=max(0, 1 - float(candidates[index].sum())),
                objective_score=float(robust[index] * 100),
                expected_return=float(expected[index]),
                median_return=float(median[index]),
                probability_positive=float(positive[index]),
                probability_beating_benchmark=float(beating[index]),
                value_at_risk=float(var[index]),
                expected_shortfall=float(es[index]),
                expected_drawdown=float(es[index]),
                concentration=float(concentration[index]),
            )
            for rank, index in enumerate(order, 1)
        ]
        signature = self.monte_carlo.returns.data_signature(matrix)
        material = (
            f"{universe}|{effective_date}|{signature}|"
            f"{simulation_config.model_dump_json()}|{optimization_config.model_dump_json()}"
        )
        return OptimizationResult(
            run_id=hashlib.sha256(material.encode()).hexdigest()[:24],
            generated_at=datetime.now(UTC),
            effective_date=effective_date,
            objective=optimization_config.objective,
            candidates=output,
            configuration={
                "simulation": simulation_config.model_dump(),
                "optimization": optimization_config.model_dump(),
            },
            data_signature=signature,
            warnings=warnings,
        )

    rank_candidates = staticmethod(
        lambda candidates: sorted(candidates, key=lambda item: -item.objective_score)
    )

    @staticmethod
    def compare_candidates(
        first: OptimizationCandidate, second: OptimizationCandidate
    ) -> dict[str, float]:
        return {
            "objective_difference": first.objective_score - second.objective_score,
            "return_difference": first.expected_return - second.expected_return,
            "risk_difference": first.expected_shortfall - second.expected_shortfall,
        }

    @staticmethod
    def evaluate_robustness(
        candidate: OptimizationCandidate, stress_results: list[float]
    ) -> RobustnessResult:
        values = [candidate.objective_score, *stress_results]
        dispersion = float(np.std(values))
        stability = max(0, 100 - dispersion)
        return RobustnessResult(
            candidate_id=candidate.candidate_id,
            seed_results=[candidate.objective_score],
            lookback_results=[],
            method_results=[],
            stress_results=stress_results,
            stability_score=stability,
            fragile=dispersion > 20 or candidate.concentration > 0.5,
            warnings=["Robustez resumida; amplíe semillas para análisis profundo."],
        )

    @staticmethod
    def rebalance(
        current: dict[str, float], target: dict[str, float], capital: float, cost_bps: float
    ) -> dict[str, object]:
        symbols = set(current) | set(target)
        changes = {
            symbol: (target.get(symbol, 0) - current.get(symbol, 0)) * capital
            for symbol in symbols
        }
        turnover = sum(abs(value) for value in changes.values()) / (2 * capital)
        return {
            "changes": changes,
            "turnover": turnover,
            "estimated_cost": turnover * capital * cost_bps / 10_000,
        }

    @staticmethod
    def _scale(values: np.ndarray) -> np.ndarray:
        minimum, maximum = float(values.min()), float(values.max())
        return (
            np.full_like(values, 0.5)
            if maximum == minimum
            else (values - minimum) / (maximum - minimum)
        )
