"""Servicio de aplicación para precios manuales."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from providers.manual_price_provider import ManualPriceProvider
from repositories.price_repository import SqlPriceRepository


class MarketDataService:
    """Coordina captura, historial y confirmación de precios."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = SqlPriceRepository(session)
        self.provider = ManualPriceProvider(self.repository)

    def save_price(
        self,
        symbol: str,
        price: Decimal,
        price_date: datetime,
        notes: str | None = None,
    ) -> None:
        """Guarda y confirma un precio manual."""
        try:
            self.provider.save_price(symbol, price, price_date, notes)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def get_current_price(self, symbol: str) -> Decimal | None:
        """Obtiene el último precio."""
        return self.provider.get_current_price(symbol)

