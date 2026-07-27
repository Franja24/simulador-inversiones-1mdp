"""Punto de entrada Streamlit del Reto Actinver Tracker."""

from datetime import date
from decimal import Decimal

import streamlit as st

from config.settings import get_settings
from database.connection import SessionLocal
from database.migrations import initialize_database
from domain.portfolio import PortfolioCreate
from repositories.portfolio_repository import PortfolioRepository
from services.portfolio_service import PortfolioService
from ui import dashboard, imports, prices, reports, transactions
from utils.logging_config import configure_logging

initialize_database()
configure_logging()
settings = get_settings()
st.set_page_config(page_title="Reto Actinver Tracker", layout="wide")
st.title("Seguimiento del Reto Actinver")
st.caption(
    "Herramienta informativa para un portafolio simulado; "
    "no constituye asesoría financiera ni promete rendimientos."
)

with SessionLocal() as session:
    portfolios = PortfolioRepository(session).list_all()
    if not portfolios:
        st.info("Crea el primer portafolio para comenzar.")
        with st.form("create_portfolio"):
            name = st.text_input("Nombre", "Portafolio Reto Actinver")
            capital = st.number_input(
                "Capital inicial (MXN)",
                min_value=1.0,
                value=settings.default_initial_capital,
            )
            start = st.date_input("Fecha de inicio", value=date.today())
            benchmark = st.text_input("Índice de referencia", "^MXX")
            if st.form_submit_button("Crear portafolio"):
                PortfolioService(session).create(
                    PortfolioCreate(
                        name=name,
                        initial_capital=Decimal(str(capital)),
                        challenge_start_date=start,
                        benchmark_symbol=benchmark,
                    )
                )
                st.success("Portafolio creado.")
                st.rerun()
        st.stop()

    selected = st.sidebar.selectbox(
        "Portafolio", portfolios, format_func=lambda item: item.name
    )
    section = st.sidebar.radio(
        "Sección",
        [
            "Dashboard",
            "Operaciones",
            "Nueva operación",
            "Precios manuales",
            "Importar operaciones",
            "Reportes",
            "Configuración",
        ],
    )
    if section == "Dashboard":
        dashboard.render(session, selected.id)
    elif section == "Operaciones":
        transactions.render_history(session, selected.id)
    elif section == "Nueva operación":
        transactions.render_new(session, selected.id)
    elif section == "Precios manuales":
        prices.render(session, selected.id)
    elif section == "Importar operaciones":
        imports.render(session, selected.id)
    elif section == "Reportes":
        reports.render(session, selected.id)
    else:
        st.json(
            {
                "moneda": settings.default_currency,
                "proveedor": settings.market_data_provider,
                "peso máximo": settings.max_position_weight,
                "mínimo de emisoras": settings.min_different_symbols,
            }
        )
