"""Validación e importación atómica de operaciones CSV y Excel."""

from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pandas as pd
from pydantic import ValidationError
from sqlalchemy.orm import Session

from database.models import TransactionType
from domain.transaction import TransactionCreate
from repositories.transaction_repository import TransactionRepository
from services.portfolio_service import PortfolioService
from services.transaction_service import TransactionService
from utils.validators import BusinessRuleError

EXPECTED_COLUMNS = [
    "transaction_date",
    "transaction_type",
    "symbol",
    "company_name",
    "quantity",
    "price",
    "commission",
    "taxes",
    "strategy",
    "reason",
    "stop_loss",
    "take_profit",
    "notes",
]


@dataclass
class ImportPreview:
    """Resultado inspeccionable antes de guardar."""

    rows: list[TransactionCreate]
    errors: list[str]
    duplicate_rows: list[int]


class ImportService:
    """Lee, valida, simula y guarda lotes completos."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def read_file(self, content: bytes, filename: str) -> pd.DataFrame:
        """Lee CSV o XLSX sin escribir archivos temporales."""
        suffix = Path(filename).suffix.lower()
        if suffix == ".csv":
            return pd.read_csv(BytesIO(content))
        if suffix == ".xlsx":
            return pd.read_excel(BytesIO(content), engine="openpyxl")
        raise ValueError("Solo se admiten archivos CSV y XLSX.")

    def validate(self, frame: pd.DataFrame, portfolio_id: int) -> ImportPreview:
        """Valida columnas, filas, duplicados y efecto secuencial."""
        missing = [column for column in EXPECTED_COLUMNS if column not in frame.columns]
        if missing:
            raise ValueError(f"Faltan columnas obligatorias: {', '.join(missing)}")

        existing = self._existing_keys(portfolio_id)
        rows: list[TransactionCreate] = []
        errors: list[str] = []
        duplicates: list[int] = []
        portfolio = PortfolioService(self.session).get_required(portfolio_id)
        cash = portfolio.available_cash
        quantities = {
            item.symbol: item.total_quantity
            for item in PortfolioService(self.session).calculate_positions(portfolio_id)
        }

        for index, raw in frame.iterrows():
            row_number = int(index) + 2
            try:
                data = self._to_schema(raw, portfolio_id)
                total = data.quantity * data.price
                fees = data.commission + data.taxes
                if data.transaction_type == TransactionType.BUY:
                    cost = total + fees
                    if cost > cash:
                        raise BusinessRuleError("efectivo insuficiente")
                    cash -= cost
                    quantities[data.symbol] = quantities.get(
                        data.symbol, Decimal("0")
                    ) + data.quantity
                else:
                    available = quantities.get(data.symbol, Decimal("0"))
                    if data.quantity > available:
                        raise BusinessRuleError("títulos insuficientes")
                    cash += total - fees
                    quantities[data.symbol] = available - data.quantity
                if self._key(data) in existing:
                    duplicates.append(row_number)
                rows.append(data)
            except (ValidationError, ValueError, TypeError, BusinessRuleError) as exc:
                errors.append(f"Fila {row_number}: {exc}")
        return ImportPreview(rows, errors, duplicates)

    def execute(self, preview: ImportPreview) -> int:
        """Guarda todo el lote o revierte cada cambio si algo falla."""
        if preview.errors:
            raise BusinessRuleError("La importación contiene filas inválidas.")
        try:
            for row in preview.rows:
                TransactionService(self.session).register(row, commit=False)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return len(preview.rows)

    def template_csv(self) -> bytes:
        """Genera una plantilla CSV descargable."""
        content = str(pd.DataFrame(columns=EXPECTED_COLUMNS).to_csv(index=False))
        return content.encode("utf-8-sig")

    def template_xlsx(self) -> bytes:
        """Genera una plantilla XLSX descargable."""
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            pd.DataFrame(columns=EXPECTED_COLUMNS).to_excel(
                writer, index=False, sheet_name="Operaciones"
            )
        return output.getvalue()

    def _existing_keys(self, portfolio_id: int) -> set[tuple[object, ...]]:
        return {
            (
                item.transaction_date.replace(tzinfo=None),
                item.transaction_type.value,
                item.symbol,
                item.quantity,
                item.price,
            )
            for item in TransactionRepository(self.session).list_for_portfolio(
                portfolio_id
            )
        }

    @staticmethod
    def _key(data: TransactionCreate) -> tuple[object, ...]:
        return (
            data.transaction_date.replace(tzinfo=None),
            data.transaction_type.value,
            data.symbol,
            data.quantity,
            data.price,
        )

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return None if pd.isna(value) or value == "" else str(value)

    @staticmethod
    def _optional_decimal(value: object) -> Decimal | None:
        return None if pd.isna(value) or value == "" else Decimal(str(value))

    def _to_schema(self, row: pd.Series, portfolio_id: int) -> TransactionCreate:
        timestamp = pd.to_datetime(row["transaction_date"], errors="raise")
        return TransactionCreate(
            portfolio_id=portfolio_id,
            transaction_type=TransactionType(
                str(row["transaction_type"]).strip().upper()
            ),
            symbol=str(row["symbol"]),
            company_name=self._optional_text(row["company_name"]),
            quantity=Decimal(str(row["quantity"])),
            price=Decimal(str(row["price"])),
            commission=self._optional_decimal(row["commission"]) or Decimal("0"),
            taxes=self._optional_decimal(row["taxes"]) or Decimal("0"),
            transaction_date=timestamp.to_pydatetime(),
            strategy=self._optional_text(row["strategy"]),
            reason=self._optional_text(row["reason"]),
            stop_loss=self._optional_decimal(row["stop_loss"]),
            take_profit=self._optional_decimal(row["take_profit"]),
            notes=self._optional_text(row["notes"]),
        )
