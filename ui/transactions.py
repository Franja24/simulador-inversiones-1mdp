"""Registro e historial filtrable de operaciones."""

import hashlib
from datetime import datetime
from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session

from database.models import TransactionType
from domain.transaction import TransactionCreate
from repositories.transaction_repository import TransactionRepository
from services.transaction_service import TransactionService
from utils.validators import BusinessRuleError


def render_new(session: Session, portfolio_id: int) -> None:
    """Muestra el formulario de alta."""
    with st.form("new_transaction"):
        kind = st.selectbox("Tipo", [TransactionType.BUY, TransactionType.SELL])
        symbol = st.text_input("Emisora")
        company = st.text_input("Empresa")
        quantity = st.number_input("Cantidad", min_value=0.000001, value=1.0)
        price = st.number_input("Precio", min_value=0.01, value=1.0)
        commission = st.number_input("Comisión", min_value=0.0)
        taxes = st.number_input("Impuestos", min_value=0.0)
        strategy = st.text_input("Estrategia")
        reason = st.text_area("Motivo")
        stop_loss = st.number_input("Stop loss", min_value=0.0)
        take_profit = st.number_input("Take profit", min_value=0.0)
        notes = st.text_area("Notas")
        confirmed = st.checkbox("Confirmo que deseo guardar esta operación")
        if st.form_submit_button("Guardar"):
            if not confirmed:
                st.warning("Confirma la operación antes de guardarla.")
                return
            operation_key = hashlib.sha256(
                repr(
                    (
                        portfolio_id,
                        kind.value,
                        symbol.strip().upper(),
                        quantity,
                        price,
                        commission,
                        taxes,
                        strategy,
                        reason,
                        stop_loss,
                        take_profit,
                        notes,
                    )
                ).encode()
            ).hexdigest()
            if st.session_state.get("last_transaction_key") == operation_key:
                st.warning("Esta operación ya fue enviada en esta sesión.")
                return
            try:
                _, warnings = TransactionService(session).register(
                    TransactionCreate(
                        portfolio_id=portfolio_id,
                        transaction_type=kind,
                        symbol=symbol,
                        company_name=company or None,
                        quantity=Decimal(str(quantity)),
                        price=Decimal(str(price)),
                        commission=Decimal(str(commission)),
                        taxes=Decimal(str(taxes)),
                        transaction_date=datetime.now().astimezone(),
                        strategy=strategy or None,
                        reason=reason or None,
                        stop_loss=Decimal(str(stop_loss)) if stop_loss else None,
                        take_profit=Decimal(str(take_profit)) if take_profit else None,
                        notes=notes or None,
                    )
                )
                st.success("Operación registrada.")
                st.session_state["last_transaction_key"] = operation_key
                for warning in warnings:
                    st.warning(warning)
            except (BusinessRuleError, ValueError) as exc:
                session.rollback()
                st.error(str(exc))


def render_history(session: Session, portfolio_id: int) -> None:
    """Muestra filtros y descarga CSV del historial."""
    records = TransactionRepository(session).list_for_portfolio(portfolio_id)
    if not records:
        st.info("No hay operaciones registradas.")
        return
    frame = pd.DataFrame(
        [
            {
                "Fecha": item.transaction_date,
                "Tipo": item.transaction_type.value,
                "Emisora": item.symbol,
                "Empresa": item.company_name,
                "Cantidad": item.quantity,
                "Precio": item.price,
                "Comisión": item.commission,
                "Impuestos": item.taxes,
                "Total": item.total_amount,
                "Estrategia": item.strategy,
                "Motivo": item.reason,
                "Stop loss": item.stop_loss,
                "Take profit": item.take_profit,
                "Notas": item.notes,
            }
            for item in records
        ]
    )
    minimum = frame["Fecha"].min().date()
    maximum = frame["Fecha"].max().date()
    c1, c2, c3 = st.columns(3)
    start = c1.date_input("Fecha inicial", minimum)
    end = c2.date_input("Fecha final", maximum)
    symbol = c3.selectbox("Emisora", ["Todas", *sorted(frame["Emisora"].unique())])
    c4, c5 = st.columns(2)
    kind = c4.selectbox("Tipo", ["Todos", "BUY", "SELL"])
    strategies = sorted(value for value in frame["Estrategia"].dropna().unique())
    strategy = c5.selectbox("Estrategia", ["Todas", *strategies])
    filtered = frame[
        (frame["Fecha"].dt.date >= start) & (frame["Fecha"].dt.date <= end)
    ]
    if symbol != "Todas":
        filtered = filtered[filtered["Emisora"] == symbol]
    if kind != "Todos":
        filtered = filtered[filtered["Tipo"] == kind]
    if strategy != "Todas":
        filtered = filtered[filtered["Estrategia"] == strategy]
    st.dataframe(filtered, use_container_width=True)
    st.download_button(
        "Descargar resultado CSV",
        filtered.to_csv(index=False).encode("utf-8-sig"),
        "operaciones_filtradas.csv",
        "text/csv",
    )

