"""Monte Carlo reproducible con bootstrap correlacionado como método principal."""

from datetime import date
from typing import cast

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from config.simulation import MonteCarloConfig
from domain.simulation import (
    AssetSimulationResult,
    HorizonSimulationResult,
    PortfolioSimulationResult,
    SimulationPercentiles,
)
from services.market_regime_service import MarketRegimeService
from services.return_matrix_service import ReturnMatrixService


class MonteCarloService:
    ASSUMPTIONS = [
        "Escenarios basados en retornos históricos; no son predicciones.",
        "Los retornos se componen por sesión y no existe apalancamiento.",
        "VaR y Expected Shortfall se reportan como magnitudes positivas de pérdida.",
    ]

    def __init__(self, session: Session) -> None:
        self.session = session
        self.returns = ReturnMatrixService(session)
        self.regimes = MarketRegimeService(session)

    def simulate_asset(
        self,
        symbol: str,
        effective_date: date,
        benchmark_symbol: str,
        config: MonteCarloConfig,
    ) -> AssetSimulationResult:
        symbols = [symbol.upper(), benchmark_symbol.upper()]
        matrix = self._matrix(symbols, effective_date, config)
        warnings = self.returns.validate_history(
            matrix,
            minimum_rows=config.minimum_history_rows,
            maximum_missing_ratio=config.maximum_missing_ratio,
        )
        regime = self.regimes.calculate(benchmark_symbol, effective_date)
        horizons: list[HorizonSimulationResult] = []
        samples: dict[str, list[list[float]]] = {}
        actual_method = config.simulation_method
        for horizon in config.horizons:
            cube, used, method_warnings = self._simulate_cube(
                matrix, horizon, config
            )
            actual_method = used
            warnings.extend(method_warnings)
            asset_paths = cube[:, :, 0]
            benchmark_paths = cube[:, :, 1]
            terminal = self._terminal(asset_paths, config)
            benchmark_terminal = self._terminal(benchmark_paths, config)
            horizons.append(
                self._summarize(
                    terminal,
                    asset_paths,
                    horizon,
                    config,
                    benchmark_terminal,
                )
            )
            samples[str(horizon)] = self._sample_paths(asset_paths, config)
        confidence = min(100, len(matrix) / config.lookback_sessions * 100)
        if warnings:
            confidence = max(0, confidence - 10)
        return AssetSimulationResult(
            symbol=symbol.upper(),
            effective_date=effective_date,
            method=config.simulation_method,
            actual_method=actual_method,
            model_version=config.model_version,
            regime=regime.primary_regime,
            confidence=confidence,
            horizons=horizons,
            assumptions=self.ASSUMPTIONS,
            warnings=list(dict.fromkeys(warnings)),
            data_signature=self.returns.data_signature(matrix),
            seed=config.random_seed,
            sample_paths=samples,
        )

    def simulate_assets(
        self,
        symbols: list[str],
        effective_date: date,
        benchmark_symbol: str,
        config: MonteCarloConfig,
    ) -> list[AssetSimulationResult]:
        return [
            self.simulate_asset(item, effective_date, benchmark_symbol, config)
            for item in symbols
        ]

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
        normalized = {key.strip().upper(): value for key, value in weights.items()}
        if benchmark_symbol.upper() in normalized:
            raise ValueError("El benchmark no puede ser una posición.")
        if any(value < 0 or value > maximum_symbol_weight for value in normalized.values()):
            raise ValueError("Pesos negativos o superiores al máximo.")
        inferred_cash = 1 - sum(normalized.values()) if cash_weight is None else cash_weight
        if inferred_cash < -1e-9 or abs(sum(normalized.values()) + inferred_cash - 1) > 1e-9:
            raise ValueError("Los pesos más efectivo deben sumar 1.")
        if not allow_cash and inferred_cash > 1e-9:
            raise ValueError("El efectivo está prohibido.")
        symbols = [*normalized, benchmark_symbol.upper()]
        matrix = self._matrix(symbols, effective_date, config)
        warnings = self.returns.validate_history(
            matrix,
            minimum_rows=config.minimum_history_rows,
            maximum_missing_ratio=config.maximum_missing_ratio,
        )
        weight_vector = np.array([normalized[item] for item in normalized])
        regime = self.regimes.calculate(benchmark_symbol, effective_date)
        horizons: list[HorizonSimulationResult] = []
        sample_paths: dict[str, list[list[float]]] = {}
        actual_method = config.simulation_method
        expected_drawdowns: list[float] = []
        for horizon in config.horizons:
            cube, actual_method, method_warnings = self._simulate_cube(
                matrix, horizon, config
            )
            warnings.extend(method_warnings)
            portfolio_paths = cube[:, :, :-1] @ weight_vector
            benchmark_paths = cube[:, :, -1]
            terminal = self._terminal(portfolio_paths, config)
            benchmark_terminal = self._terminal(benchmark_paths, config)
            summary = self._summarize(
                terminal, portfolio_paths, horizon, config, benchmark_terminal
            )
            horizons.append(summary)
            expected_drawdowns.append(summary.expected_drawdown)
            sample_paths[str(horizon)] = self._sample_paths(
                portfolio_paths, config
            )
        covariance = matrix.iloc[:, :-1].cov().to_numpy()
        asset_volatility = np.sqrt(np.maximum(np.diag(covariance), 0))
        portfolio_volatility = float(
            np.sqrt(max(0, weight_vector @ covariance @ weight_vector))
        )
        weighted_volatility = float(weight_vector @ asset_volatility)
        diversification = (
            weighted_volatility / portfolio_volatility
            if portfolio_volatility > 0
            else None
        )
        marginal = covariance @ weight_vector
        contribution = weight_vector * marginal
        contribution_total = float(contribution.sum())
        risk_contributions = {
            symbol: (
                float(value / contribution_total) if contribution_total else 0
            )
            for symbol, value in zip(normalized, contribution, strict=True)
        }
        concentration = sum(value**2 for value in normalized.values()) + inferred_cash**2
        confidence = min(100, len(matrix) / config.lookback_sessions * 100)
        return PortfolioSimulationResult(
            symbols=list(normalized),
            weights=normalized,
            cash_weight=max(0, inferred_cash),
            effective_date=effective_date,
            method=config.simulation_method,
            actual_method=actual_method,
            model_version=config.model_version,
            regime=regime.primary_regime,
            confidence=max(0, confidence - (10 if warnings else 0)),
            horizons=horizons,
            diversification_ratio=diversification,
            concentration=concentration,
            expected_drawdown=float(np.mean(expected_drawdowns)),
            probability_rule_violation=0,
            risk_contributions=risk_contributions,
            assumptions=self.ASSUMPTIONS,
            warnings=list(dict.fromkeys(warnings)),
            data_signature=self.returns.data_signature(matrix),
            seed=config.random_seed,
            sample_paths=sample_paths,
        )

    def compare_methods(
        self,
        symbol: str,
        effective_date: date,
        benchmark_symbol: str,
        config: MonteCarloConfig,
    ) -> dict[str, float]:
        output: dict[str, float] = {}
        for method in [
            "independent_bootstrap", "correlated_bootstrap", "block_bootstrap",
            "parametric_normal", "parametric_student_t",
        ]:
            result = self.simulate_asset(
                symbol,
                effective_date,
                benchmark_symbol,
                config.model_copy(update={"simulation_method": method}),
            )
            output[method] = result.horizons[0].median_return
        return output

    def _matrix(
        self, symbols: list[str], effective_date: date, config: MonteCarloConfig
    ) -> pd.DataFrame:
        return self.returns.build_aligned_return_matrix(
            symbols,
            effective_date,
            lookback_sessions=config.lookback_sessions,
            return_type=config.return_type,
            winsor_lower=config.winsor_lower,
            winsor_upper=config.winsor_upper,
        )

    @staticmethod
    def _simulate_cube(
        matrix: pd.DataFrame, horizon: int, config: MonteCarloConfig
    ) -> tuple[np.ndarray, str, list[str]]:
        rng = np.random.default_rng(config.random_seed + horizon)
        values = matrix.to_numpy(dtype=float)
        count, assets = values.shape
        simulations = config.simulation_count
        method = config.simulation_method
        warnings: list[str] = []
        if method == "independent_bootstrap":
            indices = rng.integers(0, count, size=(simulations, horizon, assets))
            cube = np.take_along_axis(
                np.broadcast_to(values.T, (simulations, assets, count)),
                indices.transpose(0, 2, 1),
                axis=2,
            ).transpose(0, 2, 1)
        elif method == "correlated_bootstrap":
            probabilities = None
            if config.regime_conditioning:
                probabilities = np.linspace(1, 1.5, count)
                probabilities /= probabilities.sum()
                warnings.append(
                    "Régimen aproximado mediante ponderación de observaciones recientes."
                )
            indices = rng.choice(
                count, size=(simulations, horizon), replace=True, p=probabilities
            )
            cube = values[indices]
        elif method == "block_bootstrap":
            blocks = math_ceil(horizon / config.block_size)
            starts = rng.integers(
                0, max(1, count - config.block_size + 1),
                size=(simulations, blocks),
            )
            cube = np.empty((simulations, blocks * config.block_size, assets))
            for offset in range(config.block_size):
                cube[:, offset::config.block_size, :] = values[
                    np.minimum(starts + offset, count - 1)
                ]
            cube = cube[:, :horizon, :]
        else:
            mean = values.mean(axis=0)
            covariance = np.cov(values, rowvar=False)
            covariance = np.atleast_2d(covariance)
            eigenvalues = np.linalg.eigvalsh(covariance)
            if eigenvalues.min() <= 1e-12:
                covariance += np.eye(assets) * (abs(eigenvalues.min()) + 1e-8)
                warnings.append("Matriz de covarianza regularizada.")
            normal = rng.multivariate_normal(
                mean, covariance, size=(simulations, horizon)
            )
            if method == "parametric_student_t":
                scale = np.sqrt(
                    rng.chisquare(
                        config.student_t_degrees_freedom,
                        size=(simulations, horizon, 1),
                    )
                    / config.student_t_degrees_freedom
                )
                cube = normal / scale
            else:
                cube = normal
        return cube, method, warnings

    @staticmethod
    def _terminal(paths: np.ndarray, config: MonteCarloConfig) -> np.ndarray:
        terminal = (
            np.exp(paths.sum(axis=1)) - 1
            if config.return_type == "log"
            else np.prod(1 + paths, axis=1) - 1
        )
        costs = (config.transaction_cost_bps + config.slippage_bps) / 10_000
        return cast(np.ndarray, np.maximum(-1, terminal - costs))

    @classmethod
    def _summarize(
        cls,
        terminal: np.ndarray,
        daily_paths: np.ndarray,
        horizon: int,
        config: MonteCarloConfig,
        benchmark: np.ndarray | None,
    ) -> HorizonSimulationResult:
        levels = [0.90, 0.95, 0.99]
        var = {f"{int(level * 100)}": cls.value_at_risk(terminal, level) for level in levels}
        es = {f"{int(level * 100)}": cls.expected_shortfall(terminal, level) for level in levels}
        cumulative = np.cumprod(1 + daily_paths, axis=1)
        peaks = np.maximum.accumulate(cumulative, axis=1)
        drawdowns = np.maximum(0, -(cumulative / peaks - 1).min(axis=1))
        percentiles = np.percentile(
            terminal, [1, 5, 10, 25, 50, 75, 90, 95, 99]
        )
        targets = [0.02, 0.05, 0.10, 0.15]
        return HorizonSimulationResult(
            horizon_sessions=horizon,
            simulation_count=len(terminal),
            expected_return=float(terminal.mean()),
            median_return=float(np.median(terminal)),
            standard_deviation=float(terminal.std()),
            probability_positive=float((terminal > 0).mean()),
            probability_above_target={
                f"{item:.0%}": float((terminal > item).mean()) for item in targets
            },
            probability_below_loss={
                f"{item:.0%}": float((terminal < -item).mean()) for item in targets
            },
            probability_beating_benchmark=(
                float((terminal > benchmark).mean()) if benchmark is not None else None
            ),
            value_at_risk=var["95"],
            expected_shortfall=es["95"],
            value_at_risk_levels=var,
            expected_shortfall_levels=es,
            best_simulated_return=float(terminal.max()),
            worst_simulated_return=float(terminal.min()),
            expected_drawdown=float(drawdowns.mean()),
            drawdown_p95=float(np.percentile(drawdowns, 95)),
            probability_drawdown={
                f"{item:.0%}": float((drawdowns > item).mean())
                for item in [0.05, 0.10, 0.15, 0.20]
            },
            percentiles=SimulationPercentiles(
                **dict(
                    zip(
                        ["p01", "p05", "p10", "p25", "p50", "p75", "p90", "p95", "p99"],
                        map(float, percentiles),
                        strict=True,
                    )
                )
            ),
        )

    @staticmethod
    def value_at_risk(returns: np.ndarray, confidence: float) -> float:
        return max(0.0, -float(np.quantile(returns, 1 - confidence)))

    @classmethod
    def expected_shortfall(cls, returns: np.ndarray, confidence: float) -> float:
        cutoff = -cls.value_at_risk(returns, confidence)
        tail = returns[returns <= cutoff]
        return max(0.0, -float(tail.mean())) if len(tail) else 0.0

    @staticmethod
    def _sample_paths(paths: np.ndarray, config: MonteCarloConfig) -> list[list[float]]:
        count = min(config.sample_path_count, len(paths))
        cumulative = np.cumprod(1 + paths[:count], axis=1)
        return cast(list[list[float]], cumulative.tolist())


def math_ceil(value: float) -> int:
    return int(np.ceil(value))
