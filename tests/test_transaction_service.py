"""Pruebas del registro de operaciones."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from config.settings import Settings
from database.models import TransactionType
from domain.portfolio import PortfolioCreate
from domain.transaction import TransactionCreate
from repositories.transaction_repository import TransactionRepository
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


def test_first_buy_below_concentration_limit(
    session: Session, portfolio_id: int, settings: Settings
) -> None:
    _, warnings = TransactionService(session, settings).register(
        operation(portfolio_id, TransactionType.BUY, "40000", "10")
    )
    assert warnings == []


def test_additional_buy_crosses_concentration_limit(
    session: Session, portfolio_id: int, settings: Settings
) -> None:
    service = TransactionService(session, settings)
    service.register(operation(portfolio_id, TransactionType.BUY, "30000", "10"))
    _, warnings = service.register(
        operation(portfolio_id, TransactionType.BUY, "25000", "10")
    )
    assert warnings


def test_additional_buy_stays_below_limit(
    session: Session, portfolio_id: int, settings: Settings
) -> None:
    service = TransactionService(session, settings)
    service.register(operation(portfolio_id, TransactionType.BUY, "10000", "10"))
    _, warnings = service.register(
        operation(portfolio_id, TransactionType.BUY, "10000", "10")
    )
    assert warnings == []


def test_concentration_with_multiple_symbols(
    session: Session, portfolio_id: int, settings: Settings
) -> None:
    service = TransactionService(session, settings)
    service.register(
        operation(portfolio_id, TransactionType.BUY, "30000", "10", "WALMEX.MX")
    )
    _, warnings = service.register(
        operation(portfolio_id, TransactionType.BUY, "30000", "10", "AMXL.MX")
    )
    assert warnings == []


def test_transaction_validation_rejects_bad_values(portfolio_id: int) -> None:
    with pytest.raises(ValueError):
        operation(portfolio_id, TransactionType.BUY, "-1", "10")


def test_symbol_is_normalized(session: Session, portfolio_id: int) -> None:
    transaction, _ = TransactionService(session).register(
        operation(portfolio_id, TransactionType.BUY, "1", "10", "  amxl.mx ")
    )
    assert transaction.symbol == "AMXL.MX"


def test_invalid_operation_does_not_change_cash(
    session: Session, portfolio_id: int
) -> None:
    before = PortfolioService(session).get_required(portfolio_id).available_cash
    with pytest.raises(BusinessRuleError):
        TransactionService(session).register(
            operation(portfolio_id, TransactionType.BUY, "1000001", "1")
        )
    session.rollback()
    after = PortfolioService(session).get_required(portfolio_id).available_cash
    assert after == before


def challenge_portfolio(session: Session, end_date: date | None = date(2026, 6, 30)) -> int:
    """Crea un portafolio con periodo histórico controlado."""
    return PortfolioService(session).create(
        PortfolioCreate(
            name="Reto con fechas",
            initial_capital=Decimal("1000000"),
            challenge_start_date=date(2026, 1, 1),
            challenge_end_date=end_date,
        )
    ).id


@pytest.mark.parametrize(
    "transaction_date",
    [
        datetime(2026, 1, 1, 0, 0),
        datetime(2026, 3, 15, 12, 0, tzinfo=UTC),
        datetime(2026, 6, 30, 23, 59, tzinfo=UTC),
    ],
)
def test_transaction_dates_inside_challenge_are_allowed(
    session: Session, transaction_date: datetime
) -> None:
    target = challenge_portfolio(session)
    data = operation(target, TransactionType.BUY, "1", "10").model_copy(
        update={"transaction_date": transaction_date}
    )
    TransactionService(session).register(data)


def test_transaction_before_challenge_is_rejected(session: Session) -> None:
    target = challenge_portfolio(session)
    data = operation(target, TransactionType.BUY, "1", "10").model_copy(
        update={"transaction_date": datetime(2025, 12, 31, tzinfo=UTC)}
    )
    with pytest.raises(BusinessRuleError, match="anterior al inicio"):
        TransactionService(session).register(data)


def test_transaction_after_challenge_is_rejected(session: Session) -> None:
    target = challenge_portfolio(session)
    data = operation(target, TransactionType.BUY, "1", "10").model_copy(
        update={"transaction_date": datetime(2026, 7, 1, tzinfo=UTC)}
    )
    with pytest.raises(BusinessRuleError, match="posterior al final"):
        TransactionService(session).register(data)


def test_future_transaction_is_rejected(session: Session, portfolio_id: int) -> None:
    data = operation(portfolio_id, TransactionType.BUY, "1", "10").model_copy(
        update={"transaction_date": datetime.now(UTC) + timedelta(days=1)}
    )
    with pytest.raises(BusinessRuleError, match="no puede ser futura"):
        TransactionService(session).register(data)


def test_portfolio_without_end_date_accepts_current_operation(
    session: Session,
) -> None:
    target = challenge_portfolio(session, None)
    data = operation(target, TransactionType.BUY, "1", "10")
    TransactionService(session).register(data)


def test_high_fees_affect_cash_and_cost_but_not_concentration(
    session: Session, portfolio_id: int, settings: Settings
) -> None:
    data = operation(
        portfolio_id,
        TransactionType.BUY,
        "49000",
        "10",
        commission="9000",
    ).model_copy(update={"taxes": Decimal("1000")})
    _, warnings = TransactionService(session, settings).register(data)
    portfolio = PortfolioService(session).get_required(portfolio_id)
    position = PortfolioService(session).calculate_positions(portfolio_id)[0]
    assert warnings == []
    assert portfolio.available_cash == Decimal("500000")
    assert position.invested_amount == Decimal("500000")
    assert position.average_purchase_price == Decimal("500000") / Decimal("49000")


def test_commit_false_can_be_rolled_back(session: Session, portfolio_id: int) -> None:
    service = TransactionService(session)
    service.register(
        operation(portfolio_id, TransactionType.BUY, "10", "10"), commit=False
    )
    assert len(TransactionRepository(session).list_for_portfolio(portfolio_id)) == 1
    session.rollback()
    assert TransactionRepository(session).list_for_portfolio(portfolio_id) == []
    assert (
        PortfolioService(session).get_required(portfolio_id).available_cash
        == Decimal("1000000")
    )


def test_error_after_flush_rolls_back_when_committing(
    session: Session,
    portfolio_id: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = TransactionService(session)
    original = service.portfolios.valuation
    calls = 0

    def fail_after_flush(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("fallo de recálculo")
        return original(*args, **kwargs)

    monkeypatch.setattr(service.portfolios, "valuation", fail_after_flush)
    with pytest.raises(RuntimeError, match="fallo de recálculo"):
        service.register(operation(portfolio_id, TransactionType.BUY, "10", "10"))
    assert TransactionRepository(session).list_for_portfolio(portfolio_id) == []


def test_current_value_is_consistent_after_commit(
    session: Session, portfolio_id: int
) -> None:
    service = TransactionService(session)
    service.register(operation(portfolio_id, TransactionType.BUY, "100", "10"))
    portfolio = PortfolioService(session).get_required(portfolio_id)
    assert portfolio.current_value == PortfolioService(session).valuation(portfolio_id)[
        "total"
    ]
