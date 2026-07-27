"""Pruebas de valoración con precios manuales."""

from decimal import Decimal

from sqlalchemy.orm import Session

from database.models import TransactionType
from repositories.price_repository import PriceRepository
from services.analytics_service import AnalyticsService
from services.transaction_service import TransactionService
from tests.test_transaction_service import operation


def test_unrealized_profit_and_return(session: Session, portfolio_id: int) -> None:
    TransactionService(session).register(
        operation(portfolio_id, TransactionType.BUY, "100", "10")
    )
    prices = PriceRepository({"AMXL.MX": Decimal("12")})
    summary = AnalyticsService(session).summary(portfolio_id, prices)
    assert summary["unrealized"] == Decimal("200")
    assert summary["total"] == Decimal("1000200")
    assert summary["return_percentage"] == Decimal("0.0200")

