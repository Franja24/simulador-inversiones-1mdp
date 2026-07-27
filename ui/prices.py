"""Captura e historial de precios manuales."""

from datetime import datetime, timedelta
from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session

from repositories.price_repository import SqlPriceRepository
from services.market_data_service import MarketDataService
from services.portfolio_service import PortfolioService


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
                st.warning(f"{position.symbol}: no tiene precio manual.")
            elif len(
                pd.bdate_range(last.date() + timedelta(days=1), datetime.now().date())
            ) > 1:
                st.warning(f"{position.symbol}: el precio puede estar desactualizado.")
        with st.form("manual_price"):
            symbol = st.selectbox("Emisora", [item.symbol for item in positions])
            price = st.number_input("Precio actual", min_value=0.01)
            price_date = st.datetime_input("Fecha y hora", value=datetime.now())
            notes = st.text_area("Notas")
            if st.form_submit_button("Guardar precio"):
                MarketDataService(session).save_price(
                    symbol, Decimal(str(price)), price_date, notes or None
                )
                st.success("Precio guardado; la valoración fue actualizada.")
                st.rerun()
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
