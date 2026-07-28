"""Interfaz explicable del Actinver Quant Score."""

from datetime import date

import pandas as pd
import streamlit as st
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from config.quant_score import QuantScoreConfig
from database.models import MarketHistoryModel
from services.quant_report_service import QuantReportService
from services.quant_score_service import QuantScoreService


def render(session: Session, benchmark_symbol: str) -> None:
    st.header("Actinver Quant Score (AQS)")
    st.caption(
        "Herramienta cuantitativa informativa. No garantiza rendimientos y no "
        "constituye asesoría financiera."
    )
    local_symbols = list(
        session.scalars(
            select(distinct(MarketHistoryModel.symbol)).order_by(
                MarketHistoryModel.symbol
            )
        )
    )
    default = ", ".join(item for item in local_symbols if item != benchmark_symbol)
    symbols_text = st.text_area("Universo local", default)
    effective_date = st.date_input("Fecha efectiva", value=date.today())
    benchmark = st.text_input("Benchmark", benchmark_symbol)
    method = st.selectbox("Normalización", ["percentile_rank", "robust_zscore"])
    use_regime = st.checkbox("Aplicar ajuste por régimen", value=True)
    if st.button("Calcular AQS", type="primary"):
        symbols = [item.strip() for item in symbols_text.split(",") if item.strip()]
        config = QuantScoreConfig(
            normalization_method=method,
            regime_adjustment_enabled=use_regime,
        )
        results = QuantScoreService(session).calculate_universe(
            symbols, effective_date, benchmark, config
        )
        ranking = QuantScoreService(session).rank_universe(results)
        st.session_state["aqs_results"] = results
        st.session_state["aqs_ranking"] = ranking
    results = st.session_state.get("aqs_results", [])
    ranking = st.session_state.get("aqs_ranking", [])
    if not results:
        st.info("Seleccione un universo con históricos locales y calcule el AQS.")
        return
    frame = pd.DataFrame([item.model_dump() for item in ranking]).drop(
        columns=["warnings"], errors="ignore"
    )
    st.dataframe(frame, use_container_width=True)
    selected = st.selectbox("Detalle de emisora", [item.symbol for item in results])
    result = next(item for item in results if item.symbol == selected)
    left, right = st.columns(2)
    left.metric("AQS final", f"{result.total_score:.1f}")
    right.metric("Confianza", f"{result.confidence:.1f}")
    st.write(
        f"Base **{result.base_score:.1f}** · ajuste de régimen "
        f"**{result.regime_adjustment:+.1f}** · {result.classification}"
    )
    st.dataframe(
        pd.DataFrame([item.model_dump() for item in result.components]),
        use_container_width=True,
    )
    for warning in result.warnings:
        st.warning(warning)
    st.download_button(
        "Descargar ranking CSV",
        QuantReportService.ranking_csv(ranking),
        "ranking_aqs.csv",
        "text/csv",
    )
