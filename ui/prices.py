"""Captura e historial de precios manuales."""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session

from repositories.price_repository import SqlPriceRepository
from services.market_data_service import MarketDataService
from services.portfolio_service import PortfolioService
from utils.dates import is_stale_price


def render(session: Session, portfolio_id: int) -> None:
    """Muestra posiciones, captura e historial."""
    repository = SqlPriceRepository(session)
    positions = PortfolioService(session).calculate_positions(portfolio_id, repository)
    if not positions:
        st.info("No hay posiciones abiertas para actualizar.")
    else:
        st.subheader("Precios de posiciones abiertas")
        for position in positions:
            last = repository.get_last_update_time(position.symbol)
            if last is None:
                st.warning(
                    f"{position.symbol}: sin precio manual; la valoración usa "
                    "el costo promedio contable."
                )
            elif is_stale_price(last, datetime.now(UTC)):
                st.warning(f"{position.symbol}: el precio puede estar desactualizado.")
            else:
                st.caption(
                    f"{position.symbol}: última actualización "
                    f"{last.astimezone():%Y-%m-%d %H:%M}"
                )
        with st.form("manual_price"):
            symbol = st.selectbox("Emisora", [item.symbol for item in positions])
            price = st.number_input("Precio actual", min_value=0.01)
            price_date = st.datetime_input("Fecha y hora", value=datetime.now())
            notes = st.text_area("Notas")
            if st.form_submit_button("Guardar precio"):
                price_key = hashlib.sha256(
                    repr((symbol, price, price_date, notes)).encode()
                ).hexdigest()
                if st.session_state.get("last_price_key") == price_key:
                    st.warning("Este precio ya fue enviado en esta sesión.")
                    return
                try:
                    MarketDataService(session).save_price(
                        symbol, Decimal(str(price)), price_date, notes or None
                    )
                    st.session_state["last_price_key"] = price_key
                    st.success("Precio guardado; la valoración fue actualizada.")
                    st.rerun()
                except Exception as exc:
                    session.rollback()
                    st.error(f"No se pudo guardar el precio: {exc}")
    history = repository.list_all()
    if history:
        st.subheader("Historial")
        symbols = ["Todas", *sorted({item.symbol for item in history})]
        selected = st.selectbox("Filtrar historial", symbols)
        records = history if selected == "Todas" else repository.list_all(selected)
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Emisora": item.symbol,
                        "Precio": item.price,
                        "Fecha": item.price_date,
                        "Proveedor": item.provider,
                        "Notas": item.notes,
                    }
                    for item in records
                ]
            ),
            use_container_width=True,
        )
