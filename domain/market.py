"""DTOs tipados de mercado independientes del proveedor."""

from datetime import date, datetime

from pydantic import BaseModel, Field


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
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int
    dividends: float = 0
    stock_splits: float = 0
    timezone: str | None = None
    provider: str

