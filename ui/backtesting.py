"""Interfaz de backtesting AQS sin lookahead."""

from datetime import date, timedelta
from typing import cast

import pandas as pd
import streamlit as st
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from config.quant_score import BacktestConfig, QuantScoreConfig
from database.models import MarketHistoryModel
from domain.quant import BacktestResult
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
    benchmark = st.text_input("Benchmark del backtest", benchmark_symbol)
    if st.button("Ejecutar backtest", type="primary"):
        result = BacktestService(session).run(
            [item.strip() for item in universe.split(",") if item.strip()],
            start,
            end,
            benchmark,
            QuantScoreConfig(),
            BacktestConfig(
                top_n=int(top_n),
                rebalance_frequency=int(frequency),
                holding_period=int(horizon),
                transaction_cost_bps=costs,
            ),
        )
        st.session_state["backtest_result"] = result
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
