"""Pruebas del registro de operaciones."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from config.settings import Settings
from database.models import TransactionType
from domain.transaction import TransactionCreate
from services.portfolio_service import PortfolioService
from services.transaction_service import TransactionService
from utils.validators import BusinessRuleError


def operation(
    portfolio_id: int,
    kind: TransactionType,
    quantity: str,
    price: str,
    symbol: str = "AMXL.MX",
    commission: str = "0",
) -> TransactionCreate:
    """Construye una operación válida."""
    return TransactionCreate(
        portfolio_id=portfolio_id,
        transaction_type=kind,
        symbol=symbol,
        company_name="América Móvil",
        quantity=Decimal(quantity),
        price=Decimal(price),
        commission=Decimal(commission),
        transaction_date=datetime.now(UTC),
    )


def test_register_buy_updates_cash(session: Session, portfolio_id: int) -> None:
    transaction, warnings = TransactionService(session).register(
        operation(portfolio_id, TransactionType.BUY, "100", "20", commission="10")
    )
    portfolio = PortfolioService(session).get_required(portfolio_id)
    assert transaction.total_amount == Decimal("2010.00")
    assert portfolio.available_cash == Decimal("997990.00")
    assert warnings == []


def test_additional_buy_calculates_weighted_average(
    session: Session, portfolio_id: int
) -> None:
    service = TransactionService(session)
    service.register(operation(portfolio_id, TransactionType.BUY, "100", "10"))
    service.register(operation(portfolio_id, TransactionType.BUY, "100", "20"))
    position = PortfolioService(session).calculate_positions(portfolio_id)[0]
    assert position.total_quantity == Decimal("200")
    assert position.average_purchase_price == Decimal("15")


def test_partial_sale_and_realized_profit(session: Session, portfolio_id: int) -> None:
    service = TransactionService(session)
    service.register(operation(portfolio_id, TransactionType.BUY, "100", "10"))
    service.register(
        operation(portfolio_id, TransactionType.SELL, "40", "15", commission="10")
    )
    portfolio_service = PortfolioService(session)
    position = portfolio_service.calculate_positions(portfolio_id)[0]
    assert position.total_quantity == Decimal("60")
    assert position.average_purchase_price == Decimal("10")
    assert portfolio_service.realized_profit_loss(portfolio_id) == Decimal("190")


def test_insufficient_cash_is_rejected(session: Session, portfolio_id: int) -> None:
    with pytest.raises(BusinessRuleError, match="Efectivo insuficiente"):
        TransactionService(session).register(
            operation(portfolio_id, TransactionType.BUY, "1000001", "1")
        )


def test_overselling_is_rejected(session: Session, portfolio_id: int) -> None:
    service = TransactionService(session)
    service.register(operation(portfolio_id, TransactionType.BUY, "10", "10"))
    with pytest.raises(BusinessRuleError, match="títulos suficientes"):
        service.register(operation(portfolio_id, TransactionType.SELL, "11", "10"))


def test_concentration_warning(session: Session, portfolio_id: int, settings: Settings) -> None:
    _, warnings = TransactionService(session, settings).register(
        operation(portfolio_id, TransactionType.BUY, "60000", "10")
    )
    assert warnings


def test_transaction_validation_rejects_bad_values(portfolio_id: int) -> None:
    with pytest.raises(ValueError):
        operation(portfolio_id, TransactionType.BUY, "-1", "10")

