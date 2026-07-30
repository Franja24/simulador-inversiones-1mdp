"""Validaciones finales de riesgo, auditoría y eficiencia antes de ML."""

import json

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.simulation import MonteCarloConfig, PortfolioOptimizationConfig
from database.models import monte_carlo_runs
from services.model_status_service import ModelStatusService
from services.monte_carlo_service import MonteCarloService
from services.portfolio_optimization_service import PortfolioOptimizationService
from services.risk_metrics_service import (
    expected_shortfall,
    path_drawdowns,
    round_trip_cost_rate,
    value_at_risk,
)
from services.simulation_report_service import SimulationReportService
from services.simulation_service import SimulationService
from tests.test_phase4_quant import seed_quant_history


def test_known_var_expected_shortfall_and_drawdown() -> None:
    returns = np.array([-0.40, -0.20, -0.10, 0.00, 0.10])
    assert value_at_risk(returns, 0.80) == pytest.approx(0.24)
    assert expected_shortfall(returns, 0.80) == pytest.approx(0.40)
    paths = np.array(
        [
            [0.10, -0.20, 0.25],
            [-0.10, 0.10, 0.00],
        ]
    )
    drawdowns = path_drawdowns(paths)
    assert drawdowns[0] == pytest.approx(0.20)
    assert drawdowns[1] == pytest.approx(0.10)


def test_cost_convention_is_round_trip_and_terminal_uses_it() -> None:
    config = MonteCarloConfig(
        transaction_cost_bps_per_side=10,
        slippage_bps_per_side=5,
    )
    assert round_trip_cost_rate(10, 5) == pytest.approx(0.003)
    terminal = MonteCarloService._terminal(np.zeros((2, 5)), config)
    assert terminal.tolist() == pytest.approx([-0.003, -0.003])


def test_batched_candidate_evaluation_matches_single_batch() -> None:
    rng = np.random.default_rng(5)
    cube = rng.normal(0, 0.01, size=(120, 10, 3)).astype(np.float32)
    candidates = rng.dirichlet(np.ones(3), size=17)
    benchmark = np.prod(1 + rng.normal(0, 0.01, size=(120, 10)), axis=1) - 1
    small = PortfolioOptimizationService._evaluate_in_batches(
        cube, candidates, benchmark, 0.002, 3
    )
    large = PortfolioOptimizationService._evaluate_in_batches(
        cube, candidates, benchmark, 0.002, 100
    )
    for name in small:
        assert small[name] == pytest.approx(large[name])


def test_acceptance_criteria_documents_every_configured_rule() -> None:
    config = PortfolioOptimizationConfig(
        minimum_symbols=2,
        maximum_symbols=5,
        maximum_var=0.1,
        maximum_expected_shortfall=0.2,
        maximum_concentration=0.4,
        minimum_probability_positive=0.6,
        minimum_probability_beating_benchmark=0.5,
    )
    criteria = PortfolioOptimizationService.acceptance_criteria(config)
    assert criteria["minimum_symbols"] == 2
    assert criteria["maximum_var"] == 0.1
    assert criteria["maximum_expected_shortfall"] == 0.2
    assert criteria["maximum_concentration"] == 0.4
    assert criteria["minimum_probability_positive"] == 0.6
    assert criteria["minimum_probability_beating_benchmark"] == 0.5


def test_execution_audit_is_complete_and_result_reproducible(
    session: Session,
) -> None:
    data = seed_quant_history(session, 100)
    config = MonteCarloConfig(
        horizons=[5],
        simulation_count=200,
        lookback_sessions=80,
        minimum_history_rows=40,
        sample_path_count=0,
        random_seed=19,
    )
    service = SimulationService(session)
    first = service.simulate_symbol(
        "ALFA.MX", data["ALFA.MX"][-1].date, "^MXX", config
    )
    second = MonteCarloService(session).simulate_asset(
        "ALFA.MX", data["ALFA.MX"][-1].date, "^MXX", config
    )
    assert first == second
    payload_text = session.scalar(select(monte_carlo_runs.c.payload))
    assert payload_text is not None
    payload = json.loads(payload_text)
    audit = payload["audit"]
    assert audit["version"] == "mc-1.1"
    assert audit["seed"] == 19
    assert audit["data_signature"] == first.data_signature
    assert audit["duration_ms"] >= 0
    assert audit["universe"] == ["ALFA.MX", "^MXX"]
    assert audit["restrictions"]
    assert audit["method"] == "correlated_bootstrap"
    assert audit["effective_date"] == str(data["ALFA.MX"][-1].date)


def test_report_csv_contains_acceptance_and_rejection_metadata(
    session: Session,
) -> None:
    data = seed_quant_history(session, 100)
    service = PortfolioOptimizationService(session)
    simulation = MonteCarloConfig(
        horizons=[5],
        simulation_count=200,
        lookback_sessions=80,
        minimum_history_rows=40,
    )
    optimization = PortfolioOptimizationConfig(
        candidate_count=20,
        minimum_symbols=2,
        maximum_symbols=3,
        minimum_confidence=0,
        maximum_concentration=0.20,
    )
    result = service.optimize(
        ["ALFA.MX", "BETA.MX", "GAMA.MX"],
        data["ALFA.MX"][-1].date,
        "^MXX",
        simulation,
        optimization,
    )
    repeated = service.optimize(
        ["ALFA.MX", "BETA.MX", "GAMA.MX"],
        data["ALFA.MX"][-1].date,
        "^MXX",
        simulation,
        optimization,
    )
    assert result == repeated
    csv = SimulationReportService.candidates_csv(result).decode()
    assert "REJECTED" in csv
    assert "rejection_reasons" in csv
    assert "requested_objective" in csv


def test_model_status_uses_latest_persisted_run(session: Session) -> None:
    data = seed_quant_history(session, 100)
    SimulationService(session).simulate_symbol(
        "ALFA.MX",
        data["ALFA.MX"][-1].date,
        "^MXX",
        MonteCarloConfig(
            horizons=[5],
            simulation_count=200,
            lookback_sessions=80,
            minimum_history_rows=40,
        ),
    )
    status = ModelStatusService(session).snapshot("^MXX")
    assert status["version"] == "mc-1.1"
    assert status["benchmark"] == "^MXX"
    assert status["monte_carlo_method"] == "correlated_bootstrap"
    assert status["horizon"] == "5"
