"""DTOs tipados de mercado independientes del proveedor."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

T = TypeVar("T")


@dataclass
class MarketBatchResult(Generic[T]):
    """Resultados parciales seguros de una consulta múltiple."""

    successes: dict[str, T] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


class MarketQuote(BaseModel):
    """Cotización puntual normalizada."""

    symbol: str
    price: float = Field(gt=0)
    previous_close: float | None = Field(default=None, gt=0)
    volume: int | None = Field(default=None, ge=0)
    timestamp: datetime
    currency: str = "MXN"
    timezone: str | None = None
    provider: str


class MarketBar(BaseModel):
    """Vela diaria OHLCV con eventos corporativos."""

    symbol: str
    date: date
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    adj_close: float = Field(gt=0)
    volume: int = Field(ge=0)
    dividends: float = Field(default=0, ge=0)
    stock_splits: float = Field(default=0, ge=0)
    timezone: str | None = None
    provider: str

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("La emisora es obligatoria.")
        return normalized

    @model_validator(mode="after")
    def validate_ohlc(self) -> "MarketBar":
        """Rechaza velas estructuralmente imposibles."""
        if self.high < self.low:
            raise ValueError("El máximo no puede ser menor que el mínimo.")
        if self.high < max(self.open, self.close):
            raise ValueError("El máximo debe cubrir apertura y cierre.")
        if self.low > min(self.open, self.close):
            raise ValueError("El mínimo debe cubrir apertura y cierre.")
        return self
