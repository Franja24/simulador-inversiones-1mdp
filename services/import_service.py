"""Validación e importación atómica de operaciones CSV y Excel."""

from dataclasses import dataclass, field
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pandas as pd
from pydantic import ValidationError
from sqlalchemy.orm import Session

from database.models import TransactionType
from domain.transaction import TransactionCreate
from repositories.transaction_repository import TransactionRepository
from services.audit_service import AuditService
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
    database_duplicate_rows: list[int] = field(default_factory=list)
    file_duplicate_rows: list[int] = field(default_factory=list)
    simulation_complete: bool = True
    simulation_stopped_at_row: int | None = None
    not_simulated_rows: list[int] = field(default_factory=list)

    @property
    def has_duplicates(self) -> bool:
        """Indica si existe cualquier clase de duplicado."""
        return bool(self.database_duplicate_rows or self.file_duplicate_rows)


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
        """Valida todas las filas y simula hasta el primer error de negocio.

        Los errores de formato se siguen recopilando en todo el archivo. Después
        del primer error de negocio, las filas con formato válido se marcan como
        no simuladas para evitar resultados financieros derivados engañosos.
        """
        missing = [column for column in EXPECTED_COLUMNS if column not in frame.columns]
        if missing:
            raise ValueError(f"Faltan columnas obligatorias: {', '.join(missing)}")

        database_keys = self._existing_keys(portfolio_id)
        file_keys: set[tuple[object, ...]] = set()
        rows: list[TransactionCreate] = []
        errors: list[str] = []
        database_duplicates: list[int] = []
        file_duplicates: list[int] = []
        not_simulated: list[int] = []
        simulation_active = True
        stopped_at: int | None = None
        portfolio = PortfolioService(self.session).get_required(portfolio_id)
        cash = portfolio.available_cash
        quantities = {
            item.symbol: item.total_quantity
            for item in PortfolioService(self.session).calculate_positions(portfolio_id)
        }
        transaction_service = TransactionService(self.session)

        for index, raw in frame.iterrows():
            row_number = int(index) + 2
            try:
                data = self._to_schema(raw, portfolio_id)
                key = self._key(data)
                if key in database_keys:
                    database_duplicates.append(row_number)
                if key in file_keys:
                    file_duplicates.append(row_number)
                file_keys.add(key)
                rows.append(data)
                transaction_service.validate_transaction_date(data, portfolio)
                if not simulation_active:
                    not_simulated.append(row_number)
                    continue
                cash, quantities = self._simulate_row(data, cash, quantities)
            except (ValidationError, ValueError, TypeError, BusinessRuleError) as exc:
                errors.append(f"Fila {row_number}: {exc}")
                if isinstance(exc, BusinessRuleError) and simulation_active:
                    simulation_active = False
                    stopped_at = row_number
        return ImportPreview(
            rows=rows,
            errors=errors,
            database_duplicate_rows=database_duplicates,
            file_duplicate_rows=file_duplicates,
            simulation_complete=simulation_active,
            simulation_stopped_at_row=stopped_at,
            not_simulated_rows=not_simulated,
        )

    def execute(
        self, preview: ImportPreview, *, allow_duplicates: bool = False
    ) -> int:
        """Guarda todo el lote o revierte cada cambio si algo falla."""
        portfolio_id = preview.rows[0].portfolio_id if preview.rows else None
        if preview.errors or not preview.simulation_complete:
            self._audit_rejection(portfolio_id, "validation_errors")
            raise BusinessRuleError("La importación contiene filas inválidas.")
        if preview.has_duplicates and not allow_duplicates:
            self._audit_rejection(portfolio_id, "duplicates_not_authorized")
            raise BusinessRuleError(
                "La importación contiene duplicados sin autorización explícita."
            )
        try:
            for row in preview.rows:
                TransactionService(self.session).register(row, commit=False)
            AuditService(self.session).record(
                portfolio_id,
                "IMPORT_BATCH_WITH_DUPLICATES"
                if preview.has_duplicates
                else "IMPORT_BATCH",
                {
                    "rows": len(preview.rows),
                    "database_duplicates": len(preview.database_duplicate_rows),
                    "file_duplicates": len(preview.file_duplicate_rows),
                },
            )
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            AuditService(self.session).record(
                portfolio_id,
                "IMPORT_ERROR",
                {"rows": len(preview.rows), "error_type": type(exc).__name__},
            )
            self.session.commit()
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

    def _audit_rejection(self, portfolio_id: int | None, reason: str) -> None:
        AuditService(self.session).record(
            portfolio_id, "IMPORT_REJECTED", {"reason": reason}
        )
        self.session.commit()

    @staticmethod
    def _simulate_row(
        data: TransactionCreate,
        cash: Decimal,
        quantities: dict[str, Decimal],
    ) -> tuple[Decimal, dict[str, Decimal]]:
        updated = quantities.copy()
        gross = data.quantity * data.price
        fees = data.commission + data.taxes
        if data.transaction_type == TransactionType.BUY:
            cost = gross + fees
            if cost > cash:
                raise BusinessRuleError("Efectivo insuficiente en la simulación.")
            cash -= cost
            updated[data.symbol] = updated.get(data.symbol, Decimal("0")) + data.quantity
        else:
            available = updated.get(data.symbol, Decimal("0"))
            if data.quantity > available:
                raise BusinessRuleError("Títulos insuficientes en la simulación.")
            cash += gross - fees
            updated[data.symbol] = available - data.quantity
        return cash, updated

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
