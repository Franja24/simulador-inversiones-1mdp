"""Generación y descarga de reportes."""

import streamlit as st
from sqlalchemy.orm import Session

from services.report_service import ReportService


def render(session: Session, portfolio_id: int) -> None:
    """Genera el archivo bajo demanda."""
    st.info("El reporte se guarda en data/exports y también puede descargarse.")
    if st.button("Generar reporte Excel"):
        with st.spinner("Generando reporte..."):
            path = ReportService(session).generate(portfolio_id)
        st.success(f"Reporte generado: {path.name}")
        st.download_button(
            "Descargar reporte",
            path.read_bytes(),
            path.name,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

