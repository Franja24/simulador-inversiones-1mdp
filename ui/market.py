"""Dashboard de estado del mercado y cache local."""

import streamlit as st
from sqlalchemy.orm import Session

from providers.market_provider import MarketProvider
from services.market_overview_service import MarketOverviewService
from services.market_session_service import BMVSessionService


def render(session: Session, provider: MarketProvider) -> None:
    """Muestra estado operativo sin recomendaciones."""
    service = MarketOverviewService(session, provider)
    summary = service.summary()
    columns = st.columns(6)
    columns[0].metric(
        "Mercado", "Abierto" if summary["market_open"] else "Cerrado"
    )
    columns[1].metric("Proveedor", str(summary["provider"]))
    columns[2].metric("Versión", str(summary["provider_version"]))
    columns[3].metric("Símbolos", str(summary["symbols"]))
    columns[4].metric("Registros", str(summary["rows"]))
    columns[5].metric("Errores recientes", str(summary["recent_errors"]))
    st.caption(f"Última sincronización: {summary['last_sync'] or 'Sin sincronizaciones'}")
    st.caption(BMVSessionService.DISCLAIMER)
    table = service.symbol_table()
    if table.empty:
        st.info("Aún no hay históricos almacenados.")
    else:
        st.dataframe(table, use_container_width=True)
    errors = service.recent_errors()
    if not errors.empty:
        st.subheader("Errores recientes")
        st.dataframe(errors, use_container_width=True)
    st.subheader("Cotizaciones externas")
    raw_symbols = st.text_input(
        "Símbolos separados por coma", "WALMEX.MX, CEMEXCPO.MX"
    )
    symbols = [
        symbol.strip().upper() for symbol in raw_symbols.split(",") if symbol.strip()
    ]
    if st.button("Consultar cotizaciones", disabled=not symbols):
        quotes, quote_errors = service.batch_quotes(symbols)
        if not quotes.empty:
            st.dataframe(quotes, use_container_width=True)
        for symbol, error in quote_errors.items():
            st.warning(f"{symbol}: no disponible ({error}).")
