"""Pruebas de consistencia matemática para optimización y riesgo."""

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.orm import Session

from config.simulation import MonteCarloConfig, PortfolioOptimizationConfig
from services.monte_carlo_service import MonteCarloService
from services.portfolio_optimization_service import PortfolioOptimizationService
from tests.test_phase4_quant import seed_quant_history


def simulation_config(**updates: object) -> MonteCarloConfig:
    base: dict[str, object] = {
        "simulation_count": 600,
        "lookback_sessions": 80,
        "minimum_history_rows": 40,
        "horizons": [5, 10],
        "random_seed": 11,
        "sample_path_count": 0,
    }
    base.update(updates)
    return MonteCarloConfig.model_validate(base)


def optimization_config(**updates: object) -> PortfolioOptimizationConfig:
    base: dict[str, object] = {
        "candidate_count": 250,
        "minimum_symbols": 2,
        "maximum_symbols": 3,
        "minimum_symbol_weight": 0.05,
        "maximum_symbol_weight": 0.70,
        "minimum_confidence": 0,
        "random_seed": 13,
    }
    base.update(updates)
    return PortfolioOptimizationConfig.model_validate(base)


def test_all_objectives_are_real_and_change_ranking(session: Session) -> None:
    service = PortfolioOptimizationService(session)
    arrays = {
        "expected": np.array([0.01, 0.03, 0.02]),
        "median": np.array([0.04, 0.01, 0.02]),
        "positive": np.array([0.6, 0.5, 0.9]),
        "beating": np.array([0.4, 0.8, 0.5]),
        "p75": np.array([0.1, 0.2, 0.15]),
        "var": np.array([0.01, 0.03, 0.02]),
        "expected_shortfall": np.array([0.02, 0.06, 0.04]),
        "diversification": np.array([0.5, 0.4, 0.8]),
        "weighted_aqs": np.array([90, 50, 70]),
    }
    winners: dict[str, int] = {}
    for objective in [
        "expected_return",
        "median_return",
        "probability_positive",
        "probability_beating_benchmark",
        "return_to_expected_shortfall",
        "return_to_var",
        "aqs_weighted_probability",
        "robust_competition_score",
    ]:
        score = service.calculate_objective(
            optimization_config(objective=objective), **arrays
        )
        winners[objective] = int(np.argmax(score))
    assert len(set(winners.values())) >= 3
    assert winners["expected_return"] != winners["median_return"]


def test_candidate_subsets_cash_bounds_and_impossible_rules(session: Session) -> None:
    service = PortfolioOptimizationService(session)
    symbols = [f"S{index}" for index in range(12)]
    config = optimization_config(
        candidate_count=100,
        minimum_symbols=3,
        maximum_symbols=5,
        maximum_cash_weight=0.25,
    )
    candidates = service.generate_candidates(symbols, config)
    counts = (candidates > 0).sum(axis=1)
    assert counts.min() >= 3
    assert counts.max() <= 5
    assert (candidates == 0).any()
    assert np.all(candidates.max(axis=1) <= config.maximum_symbol_weight)
    assert np.all(1 - candidates.sum(axis=1) <= config.maximum_cash_weight)
    with pytest.raises(ValueError, match="Restricciones imposibles"):
        service.generate_candidates(
            ["A", "B"],
            optimization_config(
                minimum_symbols=2,
                maximum_symbols=2,
                minimum_symbol_weight=0.1,
                maximum_symbol_weight=0.2,
                allow_cash=False,
            ),
        )


def test_filters_exclude_benchmark_aqs_confidence_liquidity_and_history(
    session: Session,
) -> None:
    data = seed_quant_history(session, 100)
    service = PortfolioOptimizationService(session)
    metrics: dict[str, dict[str, float]] = {
        "ALFA.MX": {"aqs": 90, "confidence": 90, "liquidity": 1_000_000},
        "BETA.MX": {"aqs": 20, "confidence": 90, "liquidity": 1_000_000},
        "GAMA.MX": {"aqs": 90, "confidence": 20, "liquidity": 1_000_000},
    }
    with pytest.raises(ValueError, match="menos emisoras"):
        service.optimize(
            ["ALFA.MX", "BETA.MX", "GAMA.MX", "^MXX", "SIN_DATOS"],
            data["ALFA.MX"][-1].date,
            "^MXX",
            simulation_config(),
            optimization_config(
                minimum_symbols=2,
                minimum_aqs=50,
                minimum_confidence=50,
                minimum_liquidity=100,
                excluded_symbols=["SIN_DATOS"],
            ),
            asset_metrics=metrics,
        )


def test_risk_rejections_are_saved_not_silent(session: Session) -> None:
    data = seed_quant_history(session, 100)
    result = PortfolioOptimizationService(session).optimize(
        ["ALFA.MX", "BETA.MX", "GAMA.MX"],
        data["ALFA.MX"][-1].date,
        "^MXX",
        simulation_config(),
        optimization_config(maximum_concentration=0.20),
    )
    assert result.candidates == []
    assert result.rejected_candidates
    assert all(item.reasons for item in result.rejected_candidates)
    assert result.requested_objective == result.used_objective


def test_round_trip_costs_affect_simulation_and_optimizer(session: Session) -> None:
    data = seed_quant_history(session, 100)
    effective = data["ALFA.MX"][-1].date
    service = MonteCarloService(session)
    free = service.simulate_asset(
        "ALFA.MX",
        effective,
        "^MXX",
        simulation_config(
            transaction_cost_bps_per_side=0, slippage_bps_per_side=0
        ),
    )
    costly = service.simulate_asset(
        "ALFA.MX",
        effective,
        "^MXX",
        simulation_config(
            transaction_cost_bps_per_side=25, slippage_bps_per_side=5
        ),
    )
    assert free.horizons[0].expected_return - costly.horizons[0].expected_return == pytest.approx(
        0.006
    )
    optimizer = PortfolioOptimizationService(session)
    base = optimization_config(objective="expected_return")
    free_opt = optimizer.optimize(
        ["ALFA.MX", "BETA.MX", "GAMA.MX"],
        effective,
        "^MXX",
        simulation_config(transaction_cost_bps_per_side=0),
        base,
        top_n=1,
    )
    costly_opt = optimizer.optimize(
        ["ALFA.MX", "BETA.MX", "GAMA.MX"],
        effective,
        "^MXX",
        simulation_config(transaction_cost_bps_per_side=100),
        base,
        top_n=1,
    )
    assert costly_opt.candidates[0].expected_return < free_opt.candidates[0].expected_return


def test_optimizer_drawdown_is_path_based_not_expected_shortfall(
    session: Session,
) -> None:
    data = seed_quant_history(session, 100)
    result = PortfolioOptimizationService(session).optimize(
        ["ALFA.MX", "BETA.MX", "GAMA.MX"],
        data["ALFA.MX"][-1].date,
        "^MXX",
        simulation_config(),
        optimization_config(),
        top_n=3,
    )
    assert result.candidates
    assert all(item.expected_drawdown >= 0 for item in result.candidates)
    assert all(item.drawdown_p95 >= item.expected_drawdown for item in result.candidates)


def test_historical_regime_modes_and_student_t_properties() -> None:
    bullish = np.full(100, 0.005)
    bearish = np.full(100, -0.005)
    assert MonteCarloService._historical_regime_labels(bullish)[-1] == "BULLISH"
    assert MonteCarloService._historical_regime_labels(bearish)[-1] == "BEARISH"
    matrix = pd.DataFrame(
        {
            "A": np.linspace(-0.03, 0.04, 200),
            "B": np.linspace(-0.02, 0.03, 200),
        }
    )
    student, _, _ = MonteCarloService._simulate_cube(
        matrix,
        5,
        simulation_config(
            simulation_method="parametric_student_t",
            simulation_count=10_000,
            regime_conditioning=False,
        ),
    )
    assert student.mean(axis=(0, 1)) == pytest.approx(
        matrix.mean().to_numpy(), abs=0.002
    )
    for mode in ["hard_filter", "weighted_sampling", "recency_weighted"]:
        cube, _, warnings = MonteCarloService._simulate_cube(
            matrix,
            5,
            simulation_config(regime_mode=mode),
        )
        assert cube.shape == (600, 5, 2)
        if mode == "hard_filter":
            assert isinstance(warnings, list)


def test_robustness_populates_all_dimensions_and_rebalance_math(
    session: Session,
) -> None:
    data = seed_quant_history(session, 100)
    service = PortfolioOptimizationService(session)
    result = service.optimize(
        ["ALFA.MX", "BETA.MX", "GAMA.MX"],
        data["ALFA.MX"][-1].date,
        "^MXX",
        simulation_config(),
        optimization_config(),
        top_n=1,
    )
    robustness = service.evaluate_candidate_robustness(
        result.candidates[0],
        data["ALFA.MX"][-1].date,
        "^MXX",
        simulation_config(),
    )
    assert len(robustness.seed_results) == 3
    assert len(robustness.lookback_results) == 2
    assert len(robustness.method_results) == 3
    assert robustness.stress_results

    unchanged = service.rebalance({"A": 1}, {"A": 1}, 1_000, 10)
    assert unchanged["gross_traded_value"] == 0
    complete = service.rebalance({"A": 1}, {"B": 1}, 1_000, 10)
    assert complete["gross_traded_value"] == 2_000
    assert complete["turnover"] == 1
    assert complete["estimated_cost"] == pytest.approx(2)
    assert complete["purchases"] == {"B": 1_000}
    assert complete["sales"] == {"A": 1_000}
