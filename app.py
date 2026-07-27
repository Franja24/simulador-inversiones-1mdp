"""Interfaz mínima de Streamlit para la Fase 1."""

from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import streamlit as st

from config.settings import get_settings
from database.connection import SessionLocal
from database.migrations import initialize_database
from database.models import TransactionType
from domain.portfolio import PortfolioCreate
from domain.transaction import TransactionCreate
from repositories.portfolio_repository import PortfolioRepository
from services.portfolio_service import PortfolioService
from services.transaction_service import TransactionService
from utils.logging_config import configure_logging
from utils.validators import BusinessRuleError

initialize_database()
configure_logging()
settings = get_settings()
st.set_page_config(page_title="Reto Actinver Tracker", layout="wide")
st.title("Seguimiento del Reto Actinver")
st.caption(
    "Herramienta informativa para un portafolio simulado; "
    "no constituye asesoría financiera."
)

with SessionLocal() as session:
    repository = PortfolioRepository(session)
    portfolios = repository.list_all()
    section = st.sidebar.radio("Sección", ["Dashboard", "Nueva operación", "Configuración"])

    if not portfolios:
        st.info("Crea el primer portafolio para comenzar.")
        with st.form("create_portfolio"):
            name = st.text_input("Nombre", "Portafolio Reto Actinver")
            capital = st.number_input(
                "Capital inicial (MXN)", min_value=1.0, value=settings.default_initial_capital
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
    portfolio_service = PortfolioService(session)

    if section == "Dashboard":
        summary = portfolio_service.valuation(selected.id)
        cols = st.columns(4)
        cols[0].metric("Capital inicial", f"${selected.initial_capital:,.2f}")
        cols[1].metric("Valor estimado", f"${summary['total']:,.2f}")
        cols[2].metric("Efectivo", f"${summary['cash']:,.2f}")
        cols[3].metric("Rendimiento", f"{summary['return_percentage']:.2f}%")
        positions = portfolio_service.calculate_positions(selected.id)
        if positions:
            st.dataframe(
                pd.DataFrame([item.model_dump() for item in positions]),
                use_container_width=True,
            )
        else:
            st.info("Todavía no hay posiciones abiertas.")

    elif section == "Nueva operación":
        with st.form("new_transaction"):
            transaction_type = st.selectbox("Tipo", [TransactionType.BUY, TransactionType.SELL])
            symbol = st.text_input("Emisora")
            company = st.text_input("Empresa")
            quantity = st.number_input("Cantidad", min_value=0.000001, value=1.0)
            price = st.number_input("Precio", min_value=0.01, value=1.0)
            commission = st.number_input("Comisión", min_value=0.0, value=0.0)
            taxes = st.number_input("Impuestos", min_value=0.0, value=0.0)
            strategy = st.text_input("Estrategia")
            reason = st.text_area("Motivo")
            confirmed = st.checkbox("Confirmo que deseo guardar esta operación")
            submitted = st.form_submit_button("Guardar")
            if submitted:
                if not confirmed:
                    st.warning("Confirma la operación antes de guardarla.")
                else:
                    try:
                        _, warnings = TransactionService(session).register(
                            TransactionCreate(
                                portfolio_id=selected.id,
                                transaction_type=transaction_type,
                                symbol=symbol,
                                company_name=company or None,
                                quantity=Decimal(str(quantity)),
                                price=Decimal(str(price)),
                                commission=Decimal(str(commission)),
                                taxes=Decimal(str(taxes)),
                                transaction_date=datetime.now().astimezone(),
                                strategy=strategy or None,
                                reason=reason or None,
                            )
                        )
                        st.success("Operación registrada.")
                        for warning in warnings:
                            st.warning(warning)
                    except (BusinessRuleError, ValueError) as exc:
                        session.rollback()
                        st.error(str(exc))
    else:
        st.subheader("Configuración vigente")
        st.json(
            {
                "moneda": settings.default_currency,
                "proveedor": settings.market_data_provider,
                "peso máximo": settings.max_position_weight,
                "mínimo de emisoras": settings.min_different_symbols,
            }
        )
