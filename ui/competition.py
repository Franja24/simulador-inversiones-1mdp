"""Competition Dashboard y asistente diario explicable."""

from datetime import date
from typing import cast

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session

from config.competition import CompetitionConfig
from domain.competition import CompetitionDashboard
from services.competition_intelligence_service import CompetitionIntelligenceService
from services.competition_report_service import CompetitionReportService


def render(session: Session, portfolio_id: int) -> None:
    st.header("Competition Intelligence")
    st.caption(
        "Asistente diario basado en snapshots existentes. "
        "No constituye asesoría financiera."
    )
    effective = st.date_input("Fecha efectiva", date.today(), key="competition_date")
    with st.expander("Pesos del Competition Score"):
        columns = st.columns(3)
        defaults = CompetitionConfig().weights
        weights = {
            name: columns[index % 3].number_input(
                name.replace("_", " ").title(),
                min_value=0.0,
                max_value=1.0,
                value=value,
                step=0.05,
            )
            for index, (name, value) in enumerate(defaults.items())
        }
        st.caption(f"Suma: {sum(weights.values()):.2f}")
    if st.button("Generar Competition Dashboard", type="primary"):
        try:
            config = CompetitionConfig(weights=weights)
            st.session_state["competition_dashboard"] = (
                CompetitionIntelligenceService(session).build_dashboard(
                    portfolio_id, effective, config
                )
            )
        except ValueError as exc:
            st.error(str(exc))
    stored = st.session_state.get("competition_dashboard")
    if stored is None:
        return
    dashboard = cast(CompetitionDashboard, stored)
    _dashboard_cards(dashboard)
    for warning in dashboard.warnings:
        st.warning(warning)
    st.subheader("Top Candidates")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Rank": item.rank,
                    "Símbolo": item.symbol,
                    "Competition Score": item.competition_score,
                    "AQS": item.aqs,
                    "Monte Carlo": item.monte_carlo,
                    "Momentum": item.momentum,
                    "Superar benchmark": item.probability_beating_benchmark,
                    "Liquidez": item.liquidity.score,
                    "Riesgo": item.risk_penalty,
                    "Confianza": item.confidence,
                    "Motivo": item.main_reason,
                }
                for item in dashboard.top_candidates
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
    with st.expander("Explainability"):
        for item in dashboard.top_candidates:
            st.markdown(f"**#{item.rank} {item.symbol} - {item.competition_score:.2f}**")
            st.json(item.explanation)
    st.subheader("Rebalance Advisor")
    advice = dashboard.rebalance
    st.metric("Recomendación", advice.recommendation)
    col1, col2, col3 = st.columns(3)
    col1.metric("Costo esperado", f"${advice.expected_cost:,.2f}")
    col2.metric("Beneficio esperado", f"${advice.expected_benefit:,.2f}")
    col3.metric("Turnover", f"{advice.turnover:.1%}")
    st.write(advice.justification)

    service = CompetitionIntelligenceService(session)
    brief = service.daily_brief(dashboard)
    st.subheader("Daily Brief")
    st.markdown(brief.markdown)
    report = CompetitionReportService()
    excel = report.excel(dashboard, brief)
    columns = st.columns(3)
    columns[0].download_button(
        "Daily Brief MD",
        report.markdown(brief),
        f"daily_brief_{effective}.md",
        "text/markdown",
    )
    columns[1].download_button(
        "Daily Brief PDF",
        report.pdf(brief),
        f"daily_brief_{effective}.pdf",
        "application/pdf",
    )
    columns[2].download_button(
        "Reporte Excel",
        excel,
        f"competition_{effective}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    columns = st.columns(3)
    columns[0].download_button(
        "Dashboard CSV",
        report.dashboard_csv(dashboard),
        f"competition_dashboard_{effective}.csv",
        "text/csv",
    )
    columns[1].download_button(
        "Top Candidates CSV",
        report.candidates_csv(dashboard),
        f"top_candidates_{effective}.csv",
        "text/csv",
    )
    columns[2].download_button(
        "Rebalance CSV",
        report.rebalance_csv(dashboard),
        f"rebalance_{effective}.csv",
        "text/csv",
    )


def _dashboard_cards(dashboard: CompetitionDashboard) -> None:
    cards = [
        ("Capital actual", f"${dashboard.capital_initial:,.2f}"),
        ("Valor portafolio", f"${dashboard.portfolio_value:,.2f}"),
        ("Poder de compra", f"${dashboard.buying_power:,.2f}"),
        ("Benchmark", dashboard.benchmark_symbol),
        ("Rendimiento benchmark", f"{dashboard.benchmark_return:.2%}"),
        ("Rendimiento portafolio", f"{dashboard.portfolio_return:.2%}"),
        ("Diferencia", f"{dashboard.excess_return:.2%}"),
        ("Régimen", dashboard.market_regime),
        ("Confianza", f"{dashboard.confidence:.1f}/100"),
        ("Riesgo", dashboard.risk_level),
        ("Estado del modelo", dashboard.model_status),
        (
            "Última actualización",
            str(dashboard.last_update or "Sin datos"),
        ),
    ]
    for start in range(0, len(cards), 4):
        for column, (label, value) in zip(
            st.columns(4), cards[start : start + 4], strict=True
        ):
            column.metric(label, value)
