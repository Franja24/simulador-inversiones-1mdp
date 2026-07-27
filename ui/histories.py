"""Descarga, inspección y exportación de históricos."""

from datetime import date, timedelta

import plotly.graph_objects as go
import streamlit as st
from sqlalchemy.orm import Session

from providers.market_provider import MarketProvider
from services.data_quality_service import DataQualityService
from services.history_service import HistoryService
from services.indicator_service import IndicatorService


def render(session: Session, provider: MarketProvider) -> None:
    """Muestra controles e históricos cacheados."""
    symbol = st.text_input("Símbolo", "AMXL.MX").strip().upper()
    c1, c2 = st.columns(2)
    start = c1.date_input("Fecha inicial", date.today() - timedelta(days=365))
    end = c2.date_input("Fecha final", date.today())
    history = HistoryService(session, provider)
    if st.button("Descargar o actualizar histórico"):
        try:
            with st.spinner("Sincronizando datos..."):
                added = history.update_symbol(symbol, start, end)
            st.success(f"Sincronización terminada: {added} registros nuevos.")
        except Exception as exc:
            st.error(f"No fue posible actualizar {symbol}: {exc}")
    frame = history.load_history(symbol, start, end)
    if frame.empty:
        st.info("No existe histórico local para el rango seleccionado.")
        return
    issues = DataQualityService().inspect(frame)
    for issue in issues:
        st.warning(f"{issue.message} Registros afectados: {issue.rows}")
    candle = go.Figure(
        data=[
            go.Candlestick(
                x=frame["date"],
                open=frame["open"],
                high=frame["high"],
                low=frame["low"],
                close=frame["close"],
                name=symbol,
            )
        ]
    )
    candle.update_layout(title=f"OHLC — {symbol}", xaxis_rangeslider_visible=False)
    st.plotly_chart(candle, use_container_width=True)
    volume = go.Figure(
        data=[go.Bar(x=frame["date"], y=frame["volume"], name="Volumen")]
    )
    volume.update_layout(title="Volumen")
    st.plotly_chart(volume, use_container_width=True)
    indicators = IndicatorService(session).calculate(symbol)
    if not indicators.empty:
        selected = [
            column
            for column in ("date", "sma_20", "ema_9", "rsi_14", "macd", "atr_14")
            if column in indicators
        ]
        st.subheader("Indicadores informativos")
        st.dataframe(indicators[selected].tail(20), use_container_width=True)
    st.subheader("Últimos registros")
    st.dataframe(frame.tail(20), use_container_width=True)
    st.download_button(
        "Exportar histórico CSV",
        frame.to_csv(index=False).encode("utf-8-sig"),
        f"historico_{symbol}.csv",
        "text/csv",
    )
