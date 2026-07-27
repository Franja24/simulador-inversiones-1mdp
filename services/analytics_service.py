"""Métricas básicas de la Fase 1."""

from decimal import Decimal

from sqlalchemy.orm import Session

from repositories.price_repository import PriceRepository
from services.portfolio_service import PortfolioService


class AnalyticsService:
    """Expone un resumen analítico estable para UI."""

    def __init__(self, session: Session) -> None:
        self.portfolios = PortfolioService(session)

    def summary(
        self, portfolio_id: int, prices: PriceRepository | None = None
    ) -> dict[str, Decimal]:
        """Devuelve métricas de valoración."""
        return self.portfolios.valuation(portfolio_id, prices)

