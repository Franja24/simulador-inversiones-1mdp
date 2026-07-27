"""Fixtures compartidos."""

from collections.abc import Generator
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session, sessionmaker

from config.settings import Settings
from database.connection import Base, build_engine
from domain.portfolio import PortfolioCreate
from services.portfolio_service import PortfolioService


@pytest.fixture
def session() -> Generator[Session, None, None]:
    """Sesión aislada en memoria."""
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        yield db


@pytest.fixture
def portfolio_id(session: Session) -> int:
    """Portafolio estándar de un millón de pesos."""
    portfolio = PortfolioService(session).create(
        PortfolioCreate(name="Prueba", initial_capital=Decimal("1000000"))
    )
    return portfolio.id


@pytest.fixture
def settings() -> Settings:
    """Configuración determinista."""
    return Settings(max_position_weight=0.50, min_different_symbols=5)

