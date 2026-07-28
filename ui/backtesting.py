"""Interfaz de backtesting AQS sin lookahead."""

from datetime import date, timedelta
from typing import cast

import pandas as pd
import streamlit as st
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from config.quant_score import BacktestConfig, QuantScoreConfig
from database.models import MarketHistoryModel
from domain.quant import BacktestResult, WalkForwardResult
from services.backtest_service import BacktestService
from services.quant_report_service import QuantReportService


def render(session: Session, benchmark_symbol: str) -> None:
    st.header("Backtesting AQS")
    st.caption("Las señales del cierre D se ejecutan como mínimo en D+1.")
    local = list(session.scalars(select(distinct(MarketHistoryModel.symbol))))
    universe = st.text_area(
        "Universo", ", ".join(item for item in local if item != benchmark_symbol)
    )
    selected_range = st.date_input(
        "Rango", value=(date.today() - timedelta(days=365), date.today())
    )
    if not isinstance(selected_range, tuple) or len(selected_range) != 2:
        st.info("Seleccione fecha inicial y final.")
        return
    start, end = selected_range
    col1, col2, col3 = st.columns(3)
    top_n = col1.number_input("Top N", min_value=1, value=5)
    frequency = col2.number_input("Frecuencia", min_value=1, value=5)
    horizon = col3.selectbox("Horizonte", [5, 10, 15])
    costs = st.number_input(
        "Costos (bps por lado)", min_value=0.0, value=10.0
    )
    maximum_weight = st.slider("Máximo por emisora", 0.05, 1.0, 0.25)
    allow_cash = st.checkbox("Permitir efectivo residual", value=True)
    wf1, wf2 = st.columns(2)
    calibration = wf1.number_input(
        "Sesiones de entrenamiento walk-forward", min_value=20, value=252
    )
    evaluation = wf2.number_input(
        "Sesiones de evaluación OOS", min_value=7, value=20
    )
    benchmark = st.text_input("Benchmark del backtest", benchmark_symbol)
    if frequency < horizon:
        st.error(
            "Esta versión no admite posiciones solapadas; la frecuencia de "
            "rebalanceo debe ser mayor o igual al periodo de mantenimiento."
        )
        return
    if not allow_cash and top_n * maximum_weight < 1:
        st.error("La combinación top N y peso máximo no permite invertir 100%.")
        return
    if evaluation <= horizon + 1:
        st.error(
            "La ventana OOS debe exceder el periodo de mantenimiento más una sesión."
        )
        return
    configuration = BacktestConfig(
        top_n=int(top_n),
        rebalance_frequency=int(frequency),
        holding_period=int(horizon),
        transaction_cost_bps=costs,
        maximum_symbol_weight=maximum_weight,
        allow_cash=allow_cash,
        calibration_sessions=int(calibration),
        evaluation_sessions=int(evaluation),
    )
    left, right = st.columns(2)
    if left.button("Ejecutar backtest completo", type="primary"):
        result = BacktestService(session).run(
            [item.strip() for item in universe.split(",") if item.strip()],
            start,
            end,
            benchmark,
            QuantScoreConfig(),
            configuration,
        )
        st.session_state["backtest_result"] = result
    if right.button("Ejecutar walk-forward OOS"):
        walk_forward = BacktestService(session).run_walk_forward(
            [item.strip() for item in universe.split(",") if item.strip()],
            start,
            end,
            benchmark,
            QuantScoreConfig(),
            configuration,
        )
        st.session_state["walk_forward_result"] = walk_forward
    st.info(
        "Backtest completo no equivale a validación fuera de muestra. "
        "Walk-forward concatena exclusivamente ventanas de evaluación OOS."
    )
    stored_walk_forward = st.session_state.get("walk_forward_result")
    if stored_walk_forward is not None:
        walk_forward_result = cast(WalkForwardResult, stored_walk_forward)
        st.subheader("Walk-forward fuera de muestra")
        st.line_chart(
            pd.DataFrame(walk_forward_result.oos_equity_curve)
            .set_index("date")["equity"]
        )
        st.dataframe(
            pd.DataFrame(
                [item.model_dump() for item in walk_forward_result.windows]
            ).drop(columns=["trades", "equity_curve", "benchmark_curve"]),
            use_container_width=True,
        )
        st.json(walk_forward_result.metrics.model_dump())
    stored_result = st.session_state.get("backtest_result")
    if stored_result is None:
        st.info("Configure un rango con históricos locales.")
        return
    result = cast(BacktestResult, stored_result)
    st.line_chart(pd.DataFrame(result.equity_curve).set_index("date")["equity"])
    st.dataframe(
        pd.DataFrame(
            [
                {"métrica": key, "valor": value}
                for key, value in result.metrics.model_dump().items()
            ]
        ),
        use_container_width=True,
    )
    st.subheader("Comparación")
    st.bar_chart(pd.Series(result.comparison))
    st.subheader("Operaciones simuladas")
    st.dataframe(
        pd.DataFrame([item.model_dump() for item in result.trades]),
        use_container_width=True,
    )
    for warning in result.warnings:
        st.warning(warning)
    reporter = QuantReportService()
    st.download_button(
        "Resultados CSV", reporter.backtest_csv(result), "backtest.csv", "text/csv"
    )
    st.download_button(
        "Configuración JSON",
        reporter.configuration_json(result),
        "backtest_config.json",
        "application/json",
    )
