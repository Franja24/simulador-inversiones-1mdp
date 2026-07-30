"""Interfaz informativa de Monte Carlo, optimización y escenarios."""

from datetime import date
from typing import cast

import pandas as pd
import streamlit as st
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from config.simulation import MonteCarloConfig, PortfolioOptimizationConfig
from database.models import MarketHistoryModel
from domain.simulation import OptimizationResult
from services.simulation_service import SimulationService

DISCLAIMER = (
    "Las simulaciones representan escenarios basados en datos y supuestos "
    "históricos. No predicen con certeza el comportamiento futuro y no "
    "constituyen asesoría financiera."
)


def render_monte_carlo(session: Session, benchmark_symbol: str) -> None:
    st.header("Monte Carlo")
    st.warning(DISCLAIMER)
    symbols = _symbols(session, benchmark_symbol)
    symbol = st.selectbox("Emisora", symbols)
    effective = st.date_input("Fecha efectiva", date.today())
    method = st.selectbox(
        "Método",
        [
            "correlated_bootstrap",
            "independent_bootstrap",
            "block_bootstrap",
            "parametric_normal",
            "parametric_student_t",
        ],
    )
    simulations = st.select_slider("Simulaciones", options=[2_000, 10_000, 50_000], value=2_000)
    lookback = st.number_input("Lookback", min_value=20, value=252)
    seed = st.number_input("Semilla", value=42)
    if st.button("Simular escenarios", type="primary") and symbol:
        config = MonteCarloConfig(
            simulation_method=method,
            simulation_count=int(simulations),
            lookback_sessions=int(lookback),
            minimum_history_rows=min(126, int(lookback) - 1),
            random_seed=int(seed),
        )
        st.session_state["mc_result"] = SimulationService(session).simulate_symbol(
            symbol, effective, benchmark_symbol, config
        )
    result = st.session_state.get("mc_result")
    if result is None:
        return
    rows = [
        {
            "Horizonte": item.horizon_sessions,
            "Esperado": item.expected_return,
            "Mediana": item.median_return,
            "Probabilidad positiva": item.probability_positive,
            "Superar benchmark": item.probability_beating_benchmark,
            "VaR 95%": item.value_at_risk,
            "Expected Shortfall 95%": item.expected_shortfall,
            "Drawdown esperado": item.expected_drawdown,
        }
        for item in result.horizons
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True)
    st.json({"confianza": result.confidence, "supuestos": result.assumptions})
    for warning in result.warnings:
        st.warning(warning)


def render_optimization(session: Session, benchmark_symbol: str) -> None:
    st.header("Optimización")
    st.warning(DISCLAIMER)
    available = _symbols(session, benchmark_symbol)
    universe = st.multiselect("Universo", available, default=available[:10])
    objective = st.selectbox(
        "Objetivo",
        [
            "robust_competition_score",
            "expected_return",
            "median_return",
            "probability_positive",
            "probability_beating_benchmark",
            "return_to_expected_shortfall",
            "return_to_var",
            "aqs_weighted_probability",
        ],
    )
    candidates = st.select_slider("Candidatos", options=[500, 5_000, 20_000], value=500)
    simulations = st.select_slider(
        "Simulaciones por matriz", options=[500, 2_000, 10_000], value=500
    )
    effective = st.date_input("Fecha efectiva", date.today(), key="opt_date")
    if st.button("Generar candidatos", type="primary") and universe:
        minimum = min(5, len(universe))
        result = SimulationService(session).optimize_portfolio(
            universe,
            effective,
            benchmark_symbol,
            MonteCarloConfig(
                simulation_count=int(simulations),
                minimum_history_rows=20,
                lookback_sessions=252,
                horizons=[15],
            ),
            PortfolioOptimizationConfig(
                candidate_count=int(candidates),
                minimum_symbols=minimum,
                maximum_symbols=len(universe),
                objective=objective,
            ),
        )
        st.session_state["optimization_result"] = result
    stored_result = st.session_state.get("optimization_result")
    if stored_result is not None:
        result = cast(OptimizationResult, stored_result)
        st.caption(
            f"Objetivo solicitado/utilizado: {result.requested_objective} / "
            f"{result.used_objective}. Aceptados: {len(result.candidates)}; "
            f"rechazados: {len(result.rejected_candidates)}."
        )
        st.dataframe(
            pd.DataFrame([item.model_dump() for item in result.candidates]),
            use_container_width=True,
        )
        if result.rejected_candidates:
            with st.expander("Candidatos rechazados y restricciones"):
                st.dataframe(
                    pd.DataFrame(
                        [item.model_dump() for item in result.rejected_candidates]
                    ),
                    use_container_width=True,
                )


def render_scenarios(session: Session, benchmark_symbol: str) -> None:
    st.header("Escenarios")
    st.warning(DISCLAIMER)
    available = _symbols(session, benchmark_symbol)
    selected = st.multiselect("Emisoras", available, default=available[:3])
    scenario = st.selectbox(
        "Escenario",
        ["market_-5", "market_-10", "market_-15", "main_position_-20", "adverse_combination"],
    )
    if st.button("Aplicar stress") and selected:
        weights = dict.fromkeys(selected, 1 / len(selected))
        result = SimulationService(session).stress_test(weights, scenario)
        st.metric("Impacto total", f"{result.portfolio_impact:.2%}")
        st.dataframe(
            pd.DataFrame(
                [{"Emisora": key, "Impacto": value} for key, value in result.asset_impacts.items()]
            )
        )


def _symbols(session: Session, benchmark: str) -> list[str]:
    return [
        item
        for item in session.scalars(
            select(distinct(MarketHistoryModel.symbol)).order_by(MarketHistoryModel.symbol)
        )
        if item != benchmark
    ]
