"""Pruebas de portafolio."""

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from domain.portfolio import PortfolioCreate
from services.portfolio_service import PortfolioService


def test_create_portfolio(session: Session) -> None:
    portfolio = PortfolioService(session).create(
        PortfolioCreate(name="Reto", initial_capital=Decimal("123456.78"))
    )
    assert portfolio.id is not None
    assert portfolio.available_cash == Decimal("123456.78")
    assert portfolio.current_value == Decimal("123456.78")


def test_invalid_date_range() -> None:
    with pytest.raises(ValueError, match="fecha final"):
        PortfolioCreate(
            name="Reto",
            challenge_start_date="2026-08-01",
            challenge_end_date="2026-07-01",
        )

