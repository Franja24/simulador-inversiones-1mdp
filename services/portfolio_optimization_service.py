"""Optimización restringida con objetivos reales y rechazos auditables."""

import hashlib
from datetime import UTC, date, datetime
from typing import cast

import numpy as np
from sqlalchemy.orm import Session

from config.simulation import MonteCarloConfig, PortfolioOptimizationConfig
from domain.simulation import (
    OptimizationCandidate,
    OptimizationResult,
    RejectedCandidate,
    RobustnessResult,
)
from services.monte_carlo_service import MonteCarloService
from services.risk_metrics_service import path_drawdowns, round_trip_cost_rate


class PortfolioOptimizationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.monte_carlo = MonteCarloService(session)

    def generate_candidates(
        self, symbols: list[str], config: PortfolioOptimizationConfig
    ) -> np.ndarray:
        count = len(symbols)
        if count < config.minimum_symbols:
            raise ValueError("El universo no cumple el mínimo de emisoras.")
        maximum_positions = min(config.maximum_symbols, count)
        minimum_invested = 1 - config.maximum_cash_weight if config.allow_cash else 1
        feasible = any(
            positions * config.minimum_symbol_weight <= 1
            and positions * config.maximum_symbol_weight >= minimum_invested
            for positions in range(config.minimum_symbols, maximum_positions + 1)
        )
        if not feasible:
            raise ValueError("Restricciones imposibles para el universo seleccionado.")
        rng = np.random.default_rng(config.random_seed)
        output: list[np.ndarray] = []
        attempts = 0
        while len(output) < config.candidate_count and attempts < config.candidate_count * 30:
            attempts += 1
            positions = int(
                rng.integers(config.minimum_symbols, maximum_positions + 1)
            )
            selected = rng.choice(count, size=positions, replace=False)
            cash = (
                float(rng.uniform(0, config.maximum_cash_weight))
                if config.allow_cash
                else 0.0
            )
            invested = 1 - cash
            if (
                positions * config.maximum_symbol_weight < invested - 1e-12
                or positions * config.minimum_symbol_weight > invested + 1e-12
            ):
                continue
            subset = rng.dirichlet(np.ones(positions)) * invested
            if (
                subset.max() > config.maximum_symbol_weight
                or subset.min() < config.minimum_symbol_weight
            ):
                continue
            candidate = np.zeros(count)
            candidate[selected] = subset
            output.append(candidate)
        if len(output) < config.candidate_count:
            raise ValueError(
                "Restricciones demasiado estrechas: no se generó el total "
                "solicitado de candidatos."
            )
        return cast(np.ndarray, np.vstack(output))

    def calculate_objective(
        self,
        config: PortfolioOptimizationConfig,
        *,
        expected: np.ndarray,
        median: np.ndarray,
        positive: np.ndarray,
        beating: np.ndarray,
        p75: np.ndarray,
        var: np.ndarray,
        expected_shortfall: np.ndarray,
        diversification: np.ndarray,
        weighted_aqs: np.ndarray,
    ) -> np.ndarray:
        objective = config.objective
        if objective == "expected_return":
            return cast(np.ndarray, expected)
        if objective == "median_return":
            return cast(np.ndarray, median)
        if objective == "probability_positive":
            return cast(np.ndarray, positive)
        if objective == "probability_beating_benchmark":
            return cast(np.ndarray, beating)
        if objective == "return_to_expected_shortfall":
            return cast(
                np.ndarray, expected / np.maximum(expected_shortfall, 1e-9)
            )
        if objective == "return_to_var":
            return cast(np.ndarray, expected / np.maximum(var, 1e-9))
        if objective == "aqs_weighted_probability":
            return cast(np.ndarray, beating * weighted_aqs / 100)
        weights = config.robust_weights
        return cast(
            np.ndarray,
            weights["probability_beating_benchmark"] * beating
            + weights["probability_positive"] * positive
            + weights["p75"] * self._scale(p75)
            + weights["median"] * self._scale(median)
            + weights["expected_shortfall"]
            * (1 - self._scale(expected_shortfall))
            + weights["diversification"] * diversification
        )

    def optimize(
        self,
        symbols: list[str],
        effective_date: date,
        benchmark_symbol: str,
        simulation_config: MonteCarloConfig,
        optimization_config: PortfolioOptimizationConfig,
        *,
        top_n: int = 20,
        asset_metrics: dict[str, dict[str, float]] | None = None,
        current_weights: dict[str, float] | None = None,
    ) -> OptimizationResult:
        metrics = asset_metrics or {}
        universe = self._filter_universe(
            symbols,
            benchmark_symbol,
            effective_date,
            simulation_config,
            optimization_config,
            metrics,
        )
        matrix = self.monte_carlo._matrix(
            [*universe, benchmark_symbol.upper()], effective_date, simulation_config
        )
        self.monte_carlo.returns.validate_history(
            matrix,
            minimum_rows=simulation_config.minimum_history_rows,
            maximum_missing_ratio=simulation_config.maximum_missing_ratio,
        )
        candidates = self.generate_candidates(universe, optimization_config)
        cube, method, warnings = self.monte_carlo._simulate_cube(
            matrix, optimization_config.horizon_sessions, simulation_config
        )
        round_trip_cost = round_trip_cost_rate(
            simulation_config.transaction_cost_bps_per_side,
            simulation_config.slippage_bps_per_side,
        )
        benchmark_terminal = np.prod(1 + cube[:, :, -1], axis=1) - 1
        evaluated = self._evaluate_in_batches(
            cube[:, :, :-1],
            candidates,
            benchmark_terminal,
            round_trip_cost,
            optimization_config.evaluation_batch_size,
        )
        expected = evaluated["expected"]
        median = evaluated["median"]
        positive = evaluated["positive"]
        beating = evaluated["beating"]
        p75 = evaluated["p75"]
        var = evaluated["var"]
        es = evaluated["expected_shortfall"]
        expected_drawdown = evaluated["expected_drawdown"]
        drawdown_p95 = evaluated["drawdown_p95"]
        concentration = (candidates**2).sum(axis=1)
        diversification = 1 - concentration
        aqs_vector = np.array(
            [metrics.get(symbol, {}).get("aqs", 50.0) for symbol in universe]
        )
        weighted_aqs = candidates @ aqs_vector / np.maximum(
            candidates.sum(axis=1), 1e-9
        )
        raw = self.calculate_objective(
            optimization_config,
            expected=expected,
            median=median,
            positive=positive,
            beating=beating,
            p75=p75,
            var=var,
            expected_shortfall=es,
            diversification=diversification,
            weighted_aqs=weighted_aqs,
        )
        current = np.array(
            [current_weights.get(item, 0) if current_weights else 0 for item in universe]
        )
        turnover = np.abs(candidates - current).sum(axis=1) / 2
        penalties = (
            optimization_config.concentration_penalty * concentration
            + optimization_config.diversification_penalty * (1 - diversification)
            + optimization_config.turnover_penalty * turnover
        )
        final = raw - penalties
        accepted: list[int] = []
        rejected: list[RejectedCandidate] = []
        for index in range(len(candidates)):
            reasons = self._risk_reasons(
                index,
                candidates,
                var,
                es,
                positive,
                beating,
                concentration,
                optimization_config,
            )
            if reasons:
                rejected.append(
                    RejectedCandidate(
                        candidate_id=self._candidate_id(candidates[index]),
                        weights=self._weights(universe, candidates[index]),
                        reasons=reasons,
                        metrics={
                            "var": float(var[index]),
                            "expected_shortfall": float(es[index]),
                            "probability_positive": float(positive[index]),
                            "probability_beating_benchmark": float(beating[index]),
                            "concentration": float(concentration[index]),
                        },
                    )
                )
            else:
                accepted.append(index)
        order = sorted(
            accepted,
            key=lambda item: (
                -final[item],
                self._candidate_id(candidates[item]),
            ),
        )[:top_n]
        output = [
            OptimizationCandidate(
                candidate_id=self._candidate_id(candidates[index]),
                rank=rank,
                weights=self._weights(universe, candidates[index]),
                cash_weight=max(0, 1 - float(candidates[index].sum())),
                objective_score=float(final[index]),
                objective_requested=optimization_config.objective,
                objective_used=optimization_config.objective,
                raw_objective_score=float(raw[index]),
                penalties={
                    "concentration": float(
                        optimization_config.concentration_penalty
                        * concentration[index]
                    ),
                    "diversification": float(
                        optimization_config.diversification_penalty
                        * (1 - diversification[index])
                    ),
                    "turnover": float(
                        optimization_config.turnover_penalty * turnover[index]
                    ),
                },
                expected_return=float(expected[index]),
                median_return=float(median[index]),
                probability_positive=float(positive[index]),
                probability_beating_benchmark=float(beating[index]),
                value_at_risk=float(var[index]),
                expected_shortfall=float(es[index]),
                expected_drawdown=float(expected_drawdown[index]),
                drawdown_p95=float(drawdown_p95[index]),
                concentration=float(concentration[index]),
                weighted_aqs=float(weighted_aqs[index]),
            )
            for rank, index in enumerate(order, 1)
        ]
        signature = self.monte_carlo.returns.data_signature(matrix)
        material = (
            f"{universe}|{effective_date}|{signature}|{method}|"
            f"{simulation_config.model_dump_json()}|{optimization_config.model_dump_json()}"
        )
        return OptimizationResult(
            run_id=hashlib.sha256(material.encode()).hexdigest()[:24],
            generated_at=datetime.combine(
                effective_date, datetime.min.time(), tzinfo=UTC
            ),
            effective_date=effective_date,
            objective=optimization_config.objective,
            requested_objective=optimization_config.objective,
            used_objective=optimization_config.objective,
            candidates=output,
            rejected_candidates=rejected,
            configuration={
                "simulation": simulation_config.model_dump(),
                "optimization": optimization_config.model_dump(),
                "filters": metrics,
                "method_used": method,
                "universe": universe,
                "acceptance_criteria": self.acceptance_criteria(
                    optimization_config
                ),
            },
            data_signature=signature,
            warnings=warnings,
        )

    def _filter_universe(
        self,
        symbols: list[str],
        benchmark: str,
        effective_date: date,
        simulation: MonteCarloConfig,
        optimization: PortfolioOptimizationConfig,
        metrics: dict[str, dict[str, float]],
    ) -> list[str]:
        excluded = {item.upper() for item in optimization.excluded_symbols}
        output: list[str] = []
        for symbol in sorted(dict.fromkeys(item.upper() for item in symbols)):
            values = metrics.get(symbol, {})
            if symbol == benchmark.upper() or symbol in excluded:
                continue
            if (
                optimization.minimum_aqs is not None
                and values.get("aqs", 0) < optimization.minimum_aqs
            ):
                continue
            if values.get("confidence", 100) < optimization.minimum_confidence:
                continue
            if (
                optimization.minimum_liquidity is not None
                and values.get("liquidity", 0) < optimization.minimum_liquidity
            ):
                continue
            history = self.monte_carlo.returns.build_asset_returns(
                symbol,
                effective_date,
                lookback_sessions=simulation.lookback_sessions,
            )
            if len(history) >= simulation.minimum_history_rows:
                output.append(symbol)
        if len(output) < optimization.minimum_symbols:
            raise ValueError("Los filtros dejan menos emisoras que minimum_symbols.")
        return output

    @staticmethod
    def acceptance_criteria(
        config: PortfolioOptimizationConfig,
    ) -> dict[str, object]:
        """Criterios estructurales y de riesgo aplicados a todo candidato."""
        return {
            "minimum_symbols": config.minimum_symbols,
            "maximum_symbols": config.maximum_symbols,
            "minimum_symbol_weight": config.minimum_symbol_weight,
            "maximum_symbol_weight": config.maximum_symbol_weight,
            "allow_cash": config.allow_cash,
            "maximum_cash_weight": config.maximum_cash_weight,
            "maximum_concentration": config.maximum_concentration,
            "maximum_var": config.maximum_var,
            "maximum_expected_shortfall": config.maximum_expected_shortfall,
            "minimum_probability_positive": config.minimum_probability_positive,
            "minimum_probability_beating_benchmark": (
                config.minimum_probability_beating_benchmark
            ),
        }

    @staticmethod
    def _evaluate_in_batches(
        asset_cube: np.ndarray,
        candidates: np.ndarray,
        benchmark_terminal: np.ndarray,
        round_trip_cost: float,
        batch_size: int,
    ) -> dict[str, np.ndarray]:
        metrics: dict[str, list[np.ndarray]] = {
            key: []
            for key in [
                "expected",
                "median",
                "positive",
                "beating",
                "p75",
                "var",
                "expected_shortfall",
                "expected_drawdown",
                "drawdown_p95",
            ]
        }
        for start in range(0, len(candidates), batch_size):
            batch = candidates[start : start + batch_size].astype(
                np.float32, copy=False
            )
            daily_paths = np.einsum(
                "sha,ca->shc", asset_cube, batch, optimize=True
            )
            terminal = np.prod(1 + daily_paths, axis=1) - 1
            terminal -= batch.sum(axis=1)[None, :] * round_trip_cost
            p05 = np.percentile(terminal, 5, axis=0)
            paths_by_candidate = daily_paths.transpose(0, 2, 1).reshape(
                -1, daily_paths.shape[1]
            )
            drawdowns = path_drawdowns(paths_by_candidate).reshape(
                daily_paths.shape[0], daily_paths.shape[2]
            )
            metrics["expected"].append(terminal.mean(axis=0))
            metrics["median"].append(np.median(terminal, axis=0))
            metrics["positive"].append((terminal > 0).mean(axis=0))
            metrics["beating"].append(
                (terminal > benchmark_terminal[:, None]).mean(axis=0)
            )
            metrics["p75"].append(np.percentile(terminal, 75, axis=0))
            metrics["var"].append(np.maximum(0, -p05))
            metrics["expected_shortfall"].append(
                np.array(
                    [
                        max(
                            0,
                            -terminal[:, index][
                                terminal[:, index] <= p05[index]
                            ].mean(),
                        )
                        for index in range(batch.shape[0])
                    ]
                )
            )
            metrics["expected_drawdown"].append(drawdowns.mean(axis=0))
            metrics["drawdown_p95"].append(
                np.percentile(drawdowns, 95, axis=0)
            )
        return {key: np.concatenate(value) for key, value in metrics.items()}

    @staticmethod
    def _risk_reasons(
        index: int,
        candidates: np.ndarray,
        var: np.ndarray,
        es: np.ndarray,
        positive: np.ndarray,
        beating: np.ndarray,
        concentration: np.ndarray,
        config: PortfolioOptimizationConfig,
    ) -> list[str]:
        reasons: list[str] = []
        cash = 1 - float(candidates[index].sum())
        weights = candidates[index][candidates[index] > 0]
        if len(weights) < config.minimum_symbols:
            reasons.append("Número de posiciones inferior al mínimo")
        if len(weights) > config.maximum_symbols:
            reasons.append("Número de posiciones superior al máximo")
        if len(weights) and weights.min() < config.minimum_symbol_weight - 1e-9:
            reasons.append("Peso por emisora inferior al mínimo")
        if len(weights) and weights.max() > config.maximum_symbol_weight + 1e-9:
            reasons.append("Peso por emisora superior al máximo")
        if cash < -1e-9:
            reasons.append("Apalancamiento no permitido")
        if not config.allow_cash and cash > 1e-9:
            reasons.append("Efectivo no permitido")
        checks = [
            (config.maximum_var, var[index], "VaR excede el máximo"),
            (
                config.maximum_expected_shortfall,
                es[index],
                "Expected Shortfall excede el máximo",
            ),
        ]
        for maximum, value, message in checks:
            if maximum is not None and value > maximum:
                reasons.append(message)
        if (
            config.minimum_probability_positive is not None
            and positive[index] < config.minimum_probability_positive
        ):
            reasons.append("Probabilidad positiva inferior al mínimo")
        if (
            config.minimum_probability_beating_benchmark is not None
            and beating[index] < config.minimum_probability_beating_benchmark
        ):
            reasons.append("Probabilidad de superar benchmark inferior al mínimo")
        if cash > config.maximum_cash_weight + 1e-9:
            reasons.append("Efectivo superior al máximo")
        if (
            config.maximum_concentration is not None
            and concentration[index] > config.maximum_concentration
        ):
            reasons.append("Concentración superior al máximo")
        return reasons

    def evaluate_candidate_robustness(
        self,
        candidate: OptimizationCandidate,
        effective_date: date,
        benchmark_symbol: str,
        config: MonteCarloConfig,
    ) -> RobustnessResult:
        seed_results: list[float] = []
        lookback_results: list[float] = []
        method_results: list[float] = []
        for seed in [config.random_seed, config.random_seed + 1, config.random_seed + 2]:
            result = self.monte_carlo.simulate_portfolio(
                candidate.weights,
                effective_date,
                benchmark_symbol,
                config.model_copy(update={"random_seed": seed}),
                cash_weight=candidate.cash_weight,
            )
            seed_results.append(result.horizons[-1].median_return)
        for lookback in sorted({config.lookback_sessions, max(20, config.lookback_sessions // 2)}):
            result = self.monte_carlo.simulate_portfolio(
                candidate.weights,
                effective_date,
                benchmark_symbol,
                config.model_copy(
                    update={
                        "lookback_sessions": lookback,
                        "minimum_history_rows": min(
                            config.minimum_history_rows, lookback - 1
                        ),
                    }
                ),
                cash_weight=candidate.cash_weight,
            )
            lookback_results.append(result.horizons[-1].median_return)
        for method in [
            "correlated_bootstrap", "block_bootstrap", "parametric_student_t"
        ]:
            result = self.monte_carlo.simulate_portfolio(
                candidate.weights,
                effective_date,
                benchmark_symbol,
                config.model_copy(update={"simulation_method": method}),
                cash_weight=candidate.cash_weight,
            )
            method_results.append(result.horizons[-1].median_return)
        stress_results = [
            -0.10 * sum(candidate.weights.values()),
            -0.20 * max(candidate.weights.values()),
        ]
        values = [*seed_results, *lookback_results, *method_results, *stress_results]
        dispersion = float(np.std(values))
        stability = max(0, 100 - dispersion * 1000)
        return RobustnessResult(
            candidate_id=candidate.candidate_id,
            seed_results=seed_results,
            lookback_results=lookback_results,
            method_results=method_results,
            stress_results=stress_results,
            stability_score=stability,
            fragile=stability < 60 or candidate.concentration > 0.5,
            warnings=[],
        )

    @staticmethod
    def evaluate_robustness(
        candidate: OptimizationCandidate, stress_results: list[float]
    ) -> RobustnessResult:
        values = [candidate.objective_score, *stress_results]
        dispersion = float(np.std(values))
        stability = max(0, 100 - dispersion)
        return RobustnessResult(
            candidate_id=candidate.candidate_id,
            seed_results=[candidate.objective_score, candidate.objective_score],
            lookback_results=[candidate.objective_score],
            method_results=[candidate.objective_score],
            stress_results=stress_results,
            stability_score=stability,
            fragile=dispersion > 20 or candidate.concentration > 0.5,
            warnings=["Use evaluate_candidate_robustness para evaluación profunda."],
        )

    @staticmethod
    def rebalance(
        current: dict[str, float],
        target: dict[str, float],
        capital: float,
        cost_bps_per_side: float,
    ) -> dict[str, object]:
        if capital <= 0:
            raise ValueError("El capital debe ser positivo.")
        symbols = set(current) | set(target)
        changes = {
            symbol: (target.get(symbol, 0) - current.get(symbol, 0)) * capital
            for symbol in symbols
        }
        purchases = {key: value for key, value in changes.items() if value > 0}
        sales = {key: -value for key, value in changes.items() if value < 0}
        gross_traded = sum(abs(value) for value in changes.values())
        turnover = gross_traded / (2 * capital)
        return {
            "changes": changes,
            "purchases": purchases,
            "sales": sales,
            "gross_traded_value": gross_traded,
            "turnover": turnover,
            "estimated_cost": gross_traded * cost_bps_per_side / 10_000,
        }

    @staticmethod
    def rank_candidates(
        candidates: list[OptimizationCandidate],
    ) -> list[OptimizationCandidate]:
        return sorted(candidates, key=lambda item: -item.objective_score)

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
    def _candidate_id(candidate: np.ndarray) -> str:
        return hashlib.sha256(candidate.tobytes()).hexdigest()[:16]

    @staticmethod
    def _weights(symbols: list[str], candidate: np.ndarray) -> dict[str, float]:
        return {
            symbol: float(value)
            for symbol, value in zip(symbols, candidate, strict=True)
            if value > 0
        }

    @staticmethod
    def _scale(values: np.ndarray) -> np.ndarray:
        minimum, maximum = float(values.min()), float(values.max())
        return (
            np.full_like(values, 0.5)
            if maximum == minimum
            else (values - minimum) / (maximum - minimum)
        )
