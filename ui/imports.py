"""Flujo de importación de operaciones."""

import hashlib

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
    content = uploaded.getvalue()
    file_key = hashlib.sha256(content).hexdigest()
    try:
        frame = service.read_file(content, uploaded.name)
        preview = service.validate(frame, portfolio_id)
    except Exception as exc:
        st.error(str(exc))
        return
    st.subheader("Vista previa")
    st.dataframe(frame, use_container_width=True)
    for error in preview.errors:
        st.error(error)
    if preview.database_duplicate_rows:
        st.warning(
            "Duplicados contra la base en filas: "
            + ", ".join(str(row) for row in preview.database_duplicate_rows)
        )
    if preview.file_duplicate_rows:
        st.warning(
            "Duplicados dentro del archivo en filas: "
            + ", ".join(str(row) for row in preview.file_duplicate_rows)
        )
    if not preview.simulation_complete:
        st.warning(
            "La simulación financiera se detuvo en la fila "
            f"{preview.simulation_stopped_at_row}; filas posteriores no fueron simuladas."
        )
    confirm_duplicates = not preview.has_duplicates or st.checkbox(
        "Confirmo que deseo importar los posibles duplicados"
    )
    confirmed = st.checkbox("Confirmo la importación completa")
    already_imported = st.session_state.get("last_import_key") == file_key
    if already_imported:
        st.info("Este archivo ya fue importado en esta sesión.")
    if st.button(
        "Importar operaciones",
        disabled=bool(preview.errors) or already_imported,
    ):
        if not confirmed or not confirm_duplicates:
            st.warning("Confirma la importación y los posibles duplicados.")
            return
        try:
            count = service.execute(
                preview, allow_duplicates=confirm_duplicates
            )
            st.session_state["last_import_key"] = file_key
            st.success(f"Se importaron {count} operaciones.")
            st.rerun()
        except Exception as exc:
            st.error(f"No se pudo completar la importación: {exc}")

