"""Pruebas de persistencia manual de precios."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import AuditLogModel, ManualPriceModel, TransactionType
from repositories.price_repository import SqlPriceRepository
from services.market_data_service import MarketDataService
from services.portfolio_service import PortfolioService
from services.transaction_service import TransactionService
from tests.test_transaction_service import operation


def test_save_and_get_latest_price(session: Session) -> None:
    service = MarketDataService(session)
    now = datetime.now(UTC)
    service.save_price(" amxl.mx ", Decimal("18.20"), now - timedelta(hours=1))
    service.save_price("AMXL.MX", Decimal("18.90"), now)
    assert service.get_current_price("amxl.mx") == Decimal("18.900000")
    assert SqlPriceRepository(session).get_last_update_time("AMXL.MX") == now


def test_multiple_symbols_and_missing_price(session: Session) -> None:
    service = MarketDataService(session)
    now = datetime.now(UTC)
    service.save_price("AMXL.MX", Decimal("18"), now)
    service.save_price("WALMEX.MX", Decimal("50"), now)
    prices = service.provider.get_multiple_prices(
        ["AMXL.MX", "WALMEX.MX", "CEMEXCPO.MX"]
    )
    assert prices["AMXL.MX"] == Decimal("18.000000")
    assert prices["WALMEX.MX"] == Decimal("50.000000")
    assert prices["CEMEXCPO.MX"] is None


def test_valuation_uses_persistent_manual_price(
    session: Session, portfolio_id: int
) -> None:
    TransactionService(session).register(
        operation(portfolio_id, TransactionType.BUY, "100", "10")
    )
    service = MarketDataService(session)
    service.save_price("AMXL.MX", Decimal("12"), datetime.now(UTC))
    valuation = PortfolioService(session).valuation(
        portfolio_id, SqlPriceRepository(session)
    )
    assert valuation["total"] == Decimal("1000200")
    assert valuation["unrealized"] == Decimal("200")


def test_manual_price_is_audited(session: Session) -> None:
    MarketDataService(session).save_price(
        "AMXL.MX", Decimal("10"), datetime.now(UTC)
    )
    actions = list(session.scalars(select(AuditLogModel.action)))
    assert "MANUAL_PRICE_CREATED" in actions


def test_manual_price_error_rolls_back(
    session: Session, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    service = MarketDataService(session)

    def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        service.session.add(
            ManualPriceModel(
                symbol="ERROR.MX",
                price=Decimal("1"),
                price_date=datetime.now(UTC),
                provider="manual",
            )
        )
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(service.provider, "save_price", fail)
    with pytest.raises(RuntimeError, match="fallo simulado"):
        service.save_price("ERROR.MX", Decimal("1"), datetime.now(UTC))
    assert SqlPriceRepository(session).get("ERROR.MX") is None
