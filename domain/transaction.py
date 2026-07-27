"""Esquemas validados para operaciones."""

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from database.models import TransactionType


class TransactionCreate(BaseModel):
    """Solicitud de alta de una compra o venta."""

    portfolio_id: int
    transaction_type: TransactionType
    symbol: str = Field(min_length=1, max_length=30)
    company_name: str | None = None
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)
    commission: Decimal = Field(default=Decimal("0"), ge=0)
    taxes: Decimal = Field(default=Decimal("0"), ge=0)
    transaction_date: datetime = Field(default_factory=lambda: datetime.now(UTC))
    strategy: str | None = None
    reason: str | None = None
    stop_loss: Decimal | None = Field(default=None, gt=0)
    take_profit: Decimal | None = Field(default=None, gt=0)
    notes: str | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        """Normaliza la emisora para evitar duplicados por formato."""
        return value.strip().upper()

    @model_validator(mode="after")
    def only_buy_sell(self) -> "TransactionCreate":
        """Limita el formulario de Fase 1 a operaciones bursátiles."""
        if self.transaction_type not in {TransactionType.BUY, TransactionType.SELL}:
            raise ValueError("La Fase 1 admite únicamente BUY y SELL.")
        return self

