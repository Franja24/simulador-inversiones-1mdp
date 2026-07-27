"""Pruebas de importación CSV/XLSX y atomicidad."""

from datetime import UTC, datetime
from io import BytesIO

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from repositories.transaction_repository import TransactionRepository
from services.import_service import EXPECTED_COLUMNS, ImportService
from services.transaction_service import TransactionService


def sample_frame() -> pd.DataFrame:
    """Crea un lote válido de compra y venta parcial."""
    now = datetime.now(UTC).replace(microsecond=0)
    return pd.DataFrame(
        [
            {
                "transaction_date": now,
                "transaction_type": "BUY",
                "symbol": " amxl.mx ",
                "company_name": "América Móvil",
                "quantity": 100,
                "price": 10,
                "commission": 0,
                "taxes": 0,
                "strategy": "Momentum",
                "reason": "",
                "stop_loss": None,
                "take_profit": None,
                "notes": "",
            },
            {
                "transaction_date": now,
                "transaction_type": "SELL",
                "symbol": "AMXL.MX",
                "company_name": "América Móvil",
                "quantity": 20,
                "price": 12,
                "commission": 1,
                "taxes": 1,
                "strategy": "Momentum",
                "reason": "",
                "stop_loss": None,
                "take_profit": None,
                "notes": "",
            },
        ],
        columns=EXPECTED_COLUMNS,
    )


def test_valid_csv_import(session: Session, portfolio_id: int) -> None:
    service = ImportService(session)
    content = sample_frame().to_csv(index=False).encode()
    preview = service.validate(service.read_file(content, "operations.csv"), portfolio_id)
    assert preview.errors == []
    assert service.execute(preview) == 2
    assert len(TransactionRepository(session).list_for_portfolio(portfolio_id)) == 2


def test_valid_xlsx_import(session: Session, portfolio_id: int) -> None:
    output = BytesIO()
    frame = sample_frame()
    frame["transaction_date"] = frame["transaction_date"].dt.tz_localize(None)
    frame.to_excel(output, index=False)
    service = ImportService(session)
    preview = service.validate(
        service.read_file(output.getvalue(), "operations.xlsx"), portfolio_id
    )
    assert preview.errors == []
    assert len(preview.rows) == 2


def test_missing_columns(session: Session, portfolio_id: int) -> None:
    with pytest.raises(ValueError, match="Faltan columnas"):
        ImportService(session).validate(pd.DataFrame({"symbol": ["AMXL.MX"]}), portfolio_id)


def test_invalid_row_is_reported(session: Session, portfolio_id: int) -> None:
    frame = sample_frame()
    frame.loc[0, "price"] = -1
    preview = ImportService(session).validate(frame, portfolio_id)
    assert preview.errors


def test_duplicate_is_detected(session: Session, portfolio_id: int) -> None:
    service = ImportService(session)
    first = service.validate(sample_frame().iloc[:1], portfolio_id)
    service.execute(first)
    duplicate = service.validate(sample_frame().iloc[:1], portfolio_id)
    assert duplicate.duplicate_rows == [2]


def test_import_rolls_back_completely(
    session: Session, portfolio_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = ImportService(session)
    preview = service.validate(sample_frame(), portfolio_id)
    original = TransactionService.register
    calls = 0

    def fail_second(self, data, *, commit=True):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("fallo simulado")
        return original(self, data, commit=commit)

    monkeypatch.setattr(TransactionService, "register", fail_second)
    with pytest.raises(RuntimeError, match="fallo simulado"):
        service.execute(preview)
    assert TransactionRepository(session).list_for_portfolio(portfolio_id) == []


def test_templates_are_generated(session: Session) -> None:
    service = ImportService(session)
    assert service.template_csv().startswith(b"\xef\xbb\xbf")
    assert service.template_xlsx().startswith(b"PK")
