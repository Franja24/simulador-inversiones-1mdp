"""Flujo de importación de operaciones."""

import streamlit as st
from sqlalchemy.orm import Session

from services.import_service import ImportService


def render(session: Session, portfolio_id: int) -> None:
    """Valida, previsualiza y confirma una importación."""
    service = ImportService(session)
    c1, c2 = st.columns(2)
    c1.download_button(
        "Plantilla CSV", service.template_csv(), "plantilla_operaciones.csv", "text/csv"
    )
    c2.download_button(
        "Plantilla XLSX",
        service.template_xlsx(),
        "plantilla_operaciones.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    uploaded = st.file_uploader("Selecciona un archivo", type=["csv", "xlsx"])
    if uploaded is None:
        return
    try:
        frame = service.read_file(uploaded.getvalue(), uploaded.name)
        preview = service.validate(frame, portfolio_id)
    except ValueError as exc:
        st.error(str(exc))
        return
    st.subheader("Vista previa")
    st.dataframe(frame, use_container_width=True)
    for error in preview.errors:
        st.error(error)
    if preview.duplicate_rows:
        st.warning(
            "Posibles duplicados en filas: "
            + ", ".join(str(row) for row in preview.duplicate_rows)
        )
    confirm_duplicates = not preview.duplicate_rows or st.checkbox(
        "Confirmo que deseo importar los posibles duplicados"
    )
    confirmed = st.checkbox("Confirmo la importación completa")
    if st.button("Importar operaciones", disabled=bool(preview.errors)):
        if not confirmed or not confirm_duplicates:
            st.warning("Confirma la importación y los posibles duplicados.")
            return
        count = service.execute(preview)
        st.success(f"Se importaron {count} operaciones.")

