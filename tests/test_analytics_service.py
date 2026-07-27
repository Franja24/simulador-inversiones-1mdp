"""Pruebas de valoración con precios manuales."""

from decimal import Decimal

from sqlalchemy.orm import Session

from database.models import TransactionType
from repositories.price_repository import PriceRepository
from services.analytics_service import AnalyticsService
from services.portfolio_service import PortfolioService
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


def test_total_after_buy_without_market_price(
    session: Session, portfolio_id: int
) -> None:
    TransactionService(session).register(
        operation(portfolio_id, TransactionType.BUY, "100", "10", commission="10")
    )
    summary = AnalyticsService(session).summary(portfolio_id)
    assert summary["total"] == Decimal("1000000")


def test_total_after_profitable_full_sale(
    session: Session, portfolio_id: int
) -> None:
    service = TransactionService(session)
    service.register(operation(portfolio_id, TransactionType.BUY, "100", "10"))
    service.register(operation(portfolio_id, TransactionType.SELL, "100", "12"))
    summary = AnalyticsService(session).summary(portfolio_id)
    assert summary["total"] == Decimal("1000200")
    assert summary["realized"] == Decimal("200")


def test_total_after_losing_sale_with_fees(
    session: Session, portfolio_id: int
) -> None:
    service = TransactionService(session)
    service.register(operation(portfolio_id, TransactionType.BUY, "100", "10"))
    sale = operation(
        portfolio_id, TransactionType.SELL, "100", "9", commission="10"
    ).model_copy(update={"taxes": Decimal("5")})
    service.register(sale)
    summary = AnalyticsService(session).summary(portfolio_id)
    assert summary["total"] == Decimal("999885")
    assert summary["realized"] == Decimal("-115")
    assert PortfolioService(session).calculate_positions(portfolio_id) == []


def test_multiple_symbols_valuation(session: Session, portfolio_id: int) -> None:
    service = TransactionService(session)
    service.register(operation(portfolio_id, TransactionType.BUY, "100", "10"))
    service.register(
        operation(portfolio_id, TransactionType.BUY, "50", "20", "WALMEX.MX")
    )
    prices = PriceRepository(
        {"AMXL.MX": Decimal("11"), "WALMEX.MX": Decimal("18")}
    )
    summary = AnalyticsService(session).summary(portfolio_id, prices)
    assert summary["total"] == Decimal("1000000")
