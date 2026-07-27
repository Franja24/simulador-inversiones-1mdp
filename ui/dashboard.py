"""Dashboard ampliado de la Fase 2."""

from decimal import Decimal

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy.orm import Session

from repositories.price_repository import SqlPriceRepository
from repositories.transaction_repository import TransactionRepository
from services.portfolio_service import PortfolioService


def money(value: Decimal) -> str:
    """Formatea moneda mexicana."""
    return f"${value:,.2f} MXN"


def render(session: Session, portfolio_id: int) -> None:
    """Muestra valoración, posiciones y gráficas."""
    service = PortfolioService(session)
    portfolio = service.get_required(portfolio_id)
    prices = SqlPriceRepository(session)
    valuation = service.valuation(portfolio_id, prices)
    positions = service.calculate_positions(portfolio_id, prices)
    operations = TransactionRepository(session).list_for_portfolio(portfolio_id)
    best = max(positions, key=lambda item: item.unrealized_return_percentage, default=None)
    worst = min(positions, key=lambda item: item.unrealized_return_percentage, default=None)

    cards = [
        ("Capital inicial", money(portfolio.initial_capital)),
        ("Valor total", money(valuation["total"])),
        ("Efectivo", money(valuation["cash"])),
        ("Capital invertido", money(valuation["invested"])),
        ("Ganancia/Pérdida", money(valuation["profit_loss"])),
        ("Ganancia realizada", money(valuation["realized"])),
        ("Ganancia no realizada", money(valuation["unrealized"])),
        ("Rendimiento", f"{valuation['return_percentage']:.2f}%"),
        ("Mejor posición", best.symbol if best else "—"),
        ("Peor posición", worst.symbol if worst else "—"),
        ("Posiciones", str(len(positions))),
        ("Operaciones", str(len(operations))),
    ]
    for start in range(0, len(cards), 4):
        for column, (label, value) in zip(
            st.columns(4), cards[start : start + 4], strict=True
        ):
            column.metric(label, value)

    if not positions:
        st.info("Todavía no hay posiciones abiertas.")
        return
    frame = pd.DataFrame(
        [
            {
                "Emisora": item.symbol,
                "Empresa": item.company_name,
                "Cantidad": float(item.total_quantity),
                "Precio promedio": float(item.average_purchase_price),
                "Precio actual": float(item.current_price),
                "Capital invertido": float(item.invested_amount),
                "Valor de mercado": float(item.current_market_value),
                "Ganancia/Pérdida": float(item.unrealized_profit_loss),
                "Rendimiento (%)": float(item.unrealized_return_percentage),
                "Peso (%)": float(item.portfolio_weight),
                "Stop loss": float(item.stop_loss) if item.stop_loss else None,
                "Take profit": float(item.take_profit) if item.take_profit else None,
                "Último precio": item.last_price_date,
            }
            for item in positions
        ]
    )
    st.subheader("Posiciones abiertas")
    st.dataframe(
        frame.style.format(
            {
                "Precio promedio": "${:,.2f}",
                "Precio actual": "${:,.2f}",
                "Capital invertido": "${:,.2f}",
                "Valor de mercado": "${:,.2f}",
                "Ganancia/Pérdida": "${:,.2f}",
                "Rendimiento (%)": "{:.2f}%",
                "Peso (%)": "{:.2f}%",
            }
        ),
        use_container_width=True,
    )
    col1, col2 = st.columns(2)
    col1.plotly_chart(
        px.pie(frame, names="Emisora", values="Valor de mercado", title="Distribución"),
        use_container_width=True,
    )
    cash_frame = pd.DataFrame(
        {
            "Categoría": ["Efectivo", "Invertido"],
            "Valor": [float(valuation["cash"]), float(valuation["invested"])],
        }
    )
    col2.plotly_chart(
        px.pie(cash_frame, names="Categoría", values="Valor", title="Efectivo vs. invertido"),
        use_container_width=True,
    )
    col3, col4 = st.columns(2)
    col3.plotly_chart(
        px.bar(frame, x="Emisora", y="Ganancia/Pérdida", title="Ganancia por emisora"),
        use_container_width=True,
    )
    col4.plotly_chart(
        px.bar(frame, x="Emisora", y="Rendimiento (%)", title="Rendimiento por emisora"),
        use_container_width=True,
    )
