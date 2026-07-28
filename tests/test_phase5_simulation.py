"""Pruebas deterministas y offline de simulación, riesgo y optimización."""

from datetime import date
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.simulation import (
    ChallengeRulesConfig,
    MonteCarloConfig,
    PortfolioOptimizationConfig,
)
from database.models import monte_carlo_runs
from repositories.market_history_repository import MarketHistoryRepository
from services.challenge_horizon_service import ChallengeHorizonService
from services.challenge_rules_service import ChallengeRulesService
from services.monte_carlo_service import MonteCarloService
from services.portfolio_optimization_service import PortfolioOptimizationService
from services.return_matrix_service import ReturnMatrixService
from services.simulation_report_service import SimulationReportService
from services.simulation_service import SimulationService
from services.stress_test_service import StressTestService
from tests.test_phase4_quant import seed_quant_history


def fast_config(method: str = "correlated_bootstrap") -> MonteCarloConfig:
    return MonteCarloConfig(
        simulation_method=method,
        horizons=[5, 10],
        simulation_count=500,
        lookback_sessions=80,
        minimum_history_rows=40,
        sample_path_count=3,
        random_seed=7,
    )


def test_monte_carlo_configuration_validation() -> None:
    assert MonteCarloConfig().simulation_method == "correlated_bootstrap"
    with pytest.raises(ValidationError):
        MonteCarloConfig(simulation_method="magic")
    with pytest.raises(ValidationError):
        MonteCarloConfig(horizons=[0])
    with pytest.raises(ValidationError):
        MonteCarloConfig(lookback_sessions=20, block_size=20)
    with pytest.raises(ValidationError):
        PortfolioOptimizationConfig(robust_weights={"x": 0.5})


def test_return_matrix_alignment_signature_diagnostics_and_no_lookahead(
    session: Session,
) -> None:
    data = seed_quant_history(session, 100)
    cutoff = data["ALFA.MX"][80].date
    service = ReturnMatrixService(session)
    matrix = service.build_aligned_return_matrix(
        ["ALFA.MX", "BETA.MX", "^MXX"],
        cutoff,
        lookback_sessions=60,
    )
    assert len(matrix) == 60
    assert matrix.index.max() <= cutoff
    assert not matrix.isna().any().any()
    signature = service.data_signature(matrix)
    diagnostics = service.diagnostics(matrix)
    assert diagnostics["rows"] == 60
    future = data["ALFA.MX"][-1].model_copy(
        update={
            "open": 900,
            "high": 1100,
            "low": 800,
            "close": 1000,
            "adj_close": 1000,
        }
    )
    MarketHistoryRepository(session).upsert_many([future])
    session.commit()
    repeated = service.build_aligned_return_matrix(
        ["ALFA.MX", "BETA.MX", "^MXX"], cutoff, lookback_sessions=60
    )
    assert service.data_signature(repeated) == signature
    with pytest.raises(ValueError, match="insuficiente"):
        service.validate_history(matrix.head(2), minimum_rows=10, maximum_missing_ratio=0)


@pytest.mark.parametrize(
    "method",
    [
        "independent_bootstrap",
        "correlated_bootstrap",
        "block_bootstrap",
        "parametric_normal",
        "parametric_student_t",
    ],
)
def test_asset_simulation_methods_are_deterministic(
    session: Session, method: str
) -> None:
    data = seed_quant_history(session, 100)
    config = fast_config(method)
    service = MonteCarloService(session)
    first = service.simulate_asset(
        "ALFA.MX", data["ALFA.MX"][-1].date, "^MXX", config
    )
    second = service.simulate_asset(
        "ALFA.MX", data["ALFA.MX"][-1].date, "^MXX", config
    )
    assert first == second
    assert [item.horizon_sessions for item in first.horizons] == [5, 10]
    assert all(0 <= item.probability_positive <= 1 for item in first.horizons)
    assert all(item.value_at_risk >= 0 for item in first.horizons)
    assert first.sample_paths["5"]


def test_correlated_portfolio_simulation_weights_risk_and_benchmark(
    session: Session, tmp_path: Path,
) -> None:
    data = seed_quant_history(session, 100)
    config = fast_config()
    service = MonteCarloService(session)
    result = service.simulate_portfolio(
        {"ALFA.MX": 0.4, "BETA.MX": 0.4},
        data["ALFA.MX"][-1].date,
        "^MXX",
        config,
        cash_weight=0.2,
        maximum_symbol_weight=0.5,
    )
    assert result.cash_weight == pytest.approx(0.2)
    assert result.concentration == pytest.approx(0.36)
    assert set(result.risk_contributions) == {"ALFA.MX", "BETA.MX"}
    assert result.horizons[0].probability_beating_benchmark is not None
    reporter = SimulationReportService()
    report = reporter.generate(result, output_dir=tmp_path)
    assert report.exists()
    assert b"ALFA" in reporter.reproducible_json(result)
    with pytest.raises(ValueError):
        service.simulate_portfolio(
            {"^MXX": 1}, data["ALFA.MX"][-1].date, "^MXX", config
        )
    with pytest.raises(ValueError):
        service.simulate_portfolio(
            {"ALFA.MX": 0.8}, data["ALFA.MX"][-1].date, "^MXX", config,
            maximum_symbol_weight=0.5,
        )


def test_var_expected_shortfall_and_constant_series() -> None:
    values = np.array([-0.20, -0.10, 0, 0.10, 0.20])
    service = MonteCarloService
    var = service.value_at_risk(values, 0.80)
    es = service.expected_shortfall(values, 0.80)
    assert var == pytest.approx(0.12)
    assert es == pytest.approx(0.20)
    assert service.value_at_risk(np.zeros(20), 0.95) == 0
    assert service.expected_shortfall(np.zeros(20), 0.95) == 0


def test_stress_rules_and_challenge_horizons() -> None:
    stress = StressTestService()
    result = stress.run_predefined({"A": 0.6, "B": 0.4}, "market_-10")
    assert result.portfolio_impact == pytest.approx(-0.10)
    assert result.total_loss == pytest.approx(0.10)
    custom = stress.run_custom_scenario(
        {"A": 0.6, "B": 0.4},
        {"A": -0.5},
        "custom",
        ChallengeRulesConfig(maximum_symbol_weight=0.55),
    )
    assert custom.damage_contribution["A"] == 1
    with pytest.raises(ValueError):
        stress.run_predefined({"A": 1}, "unknown")
    rules = ChallengeRulesService()
    violations = rules.validate_portfolio(
        {"A": 0.7}, 0.3,
        ChallengeRulesConfig(
            minimum_symbols=2,
            maximum_symbol_weight=0.5,
            maximum_cash_weight=0.2,
        ),
    )
    assert len(violations) >= 3
    assert "Cumple" in rules.explain_violations([])
    horizon = ChallengeHorizonService()
    assert horizon.recommended_horizons(20)[0] == [5, 10, 15]
    assert horizon.recommended_horizons(10)[0] == [10]
    assert horizon.recommended_horizons(3)[0] == [3]
    assert horizon.recommended_horizons(0)[0] == []
    assert horizon.remaining_sessions(date(2026, 1, 5), date(2026, 1, 9)) == 5


def test_optimization_vectorized_deterministic_and_rebalance(
    session: Session,
) -> None:
    data = seed_quant_history(session, 100)
    simulation = fast_config()
    optimization = PortfolioOptimizationConfig(
        candidate_count=300,
        minimum_symbols=3,
        maximum_symbols=3,
        minimum_symbol_weight=0.01,
        maximum_symbol_weight=0.6,
        random_seed=9,
    )
    service = PortfolioOptimizationService(session)
    first = service.optimize(
        ["ALFA.MX", "BETA.MX", "GAMA.MX"],
        data["ALFA.MX"][-1].date,
        "^MXX",
        simulation,
        optimization,
        top_n=5,
    )
    second = service.optimize(
        ["ALFA.MX", "BETA.MX", "GAMA.MX"],
        data["ALFA.MX"][-1].date,
        "^MXX",
        simulation,
        optimization,
        top_n=5,
    )
    assert first.run_id == second.run_id
    assert [item.objective_score for item in first.candidates] == [
        item.objective_score for item in second.candidates
    ]
    assert all(
        max(item.weights.values()) <= optimization.maximum_symbol_weight
        for item in first.candidates
    )
    robust = service.evaluate_robustness(first.candidates[0], [-20, 10])
    assert 0 <= robust.stability_score <= 100
    rebalance = service.rebalance(
        {"A": 0.5, "B": 0.5}, {"A": 0.4, "B": 0.6}, 1_000_000, 10
    )
    assert rebalance["turnover"] == pytest.approx(0.1)


def test_simulation_facade_persists_and_reproduces(session: Session) -> None:
    data = seed_quant_history(session, 100)
    service = SimulationService(session)
    result = service.simulate_symbol(
        "ALFA.MX", data["ALFA.MX"][-1].date, "^MXX", fast_config()
    )
    run_id = session.scalar(select(monte_carlo_runs.c.run_id))
    assert run_id is not None
    stored = service.load_run(run_id)
    assert stored is not None
    assert stored["symbol"] == result.symbol
    assert service.reproduce_run(run_id) == stored
    with pytest.raises(ValueError):
        service.reproduce_run("missing")
