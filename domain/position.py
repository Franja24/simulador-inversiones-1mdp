"""Posición calculada desde el historial."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class Position(BaseModel):
    """Representa una posición abierta calculada."""

    symbol: str
    company_name: str | None
    total_quantity: Decimal
    average_purchase_price: Decimal
    current_price: Decimal
    invested_amount: Decimal
    current_market_value: Decimal
    unrealized_profit_loss: Decimal
    unrealized_return_percentage: Decimal
    portfolio_weight: Decimal
    stop_loss: Decimal | None
    take_profit: Decimal | None
    last_updated: datetime
    last_price_date: datetime | None = None
