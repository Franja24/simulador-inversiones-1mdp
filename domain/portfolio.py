"""Esquemas de portafolio."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PortfolioCreate(BaseModel):
    """Datos necesarios para crear un portafolio."""

    name: str = Field(min_length=1, max_length=120)
    initial_capital: Decimal = Field(default=Decimal("1000000"), gt=0)
    challenge_start_date: date | None = None
    challenge_end_date: date | None = None
    benchmark_symbol: str = "^MXX"
    notes: str | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> "PortfolioCreate":
        """Comprueba el orden de las fechas del reto."""
        if (
            self.challenge_start_date
            and self.challenge_end_date
            and self.challenge_end_date < self.challenge_start_date
        ):
            raise ValueError("La fecha final no puede ser anterior a la inicial.")
        return self


class PortfolioRead(BaseModel):
    """Vista pública de un portafolio."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    initial_capital: Decimal
    available_cash: Decimal
    current_value: Decimal
    benchmark_symbol: str

