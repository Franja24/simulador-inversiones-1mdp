"""Pruebas de importación CSV/XLSX y atomicidad."""

from datetime import UTC, date, datetime, timedelta
from io import BytesIO

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import AuditLogModel, PortfolioModel
from repositories.transaction_repository import TransactionRepository
from services.import_service import EXPECTED_COLUMNS, ImportService
from services.transaction_service import TransactionService
from utils.validators import BusinessRuleError


def sample_frame() -> pd.DataFrame:
    """Crea un lote válido de compra y venta parcial."""
    now = datetime.combine(date.today(), datetime.min.time(), tzinfo=UTC).replace(
        hour=12
    )
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
    assert duplicate.database_duplicate_rows == [2]


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
    assert "IMPORT_ERROR" in list(session.scalars(select(AuditLogModel.action)))


def test_templates_are_generated(session: Session) -> None:
    service = ImportService(session)
    assert service.template_csv().startswith(b"\xef\xbb\xbf")
    assert service.template_xlsx().startswith(b"PK")


def test_duplicate_inside_csv(session: Session, portfolio_id: int) -> None:
    frame = pd.concat([sample_frame().iloc[:1]] * 2, ignore_index=True)
    content = frame.to_csv(index=False).encode()
    service = ImportService(session)
    preview = service.validate(service.read_file(content, "duplicate.csv"), portfolio_id)
    assert preview.file_duplicate_rows == [3]
    assert preview.database_duplicate_rows == []


def test_duplicate_inside_xlsx(session: Session, portfolio_id: int) -> None:
    frame = pd.concat([sample_frame().iloc[:1]] * 2, ignore_index=True)
    frame["transaction_date"] = pd.to_datetime(frame["transaction_date"]).dt.tz_localize(None)
    output = BytesIO()
    frame.to_excel(output, index=False)
    service = ImportService(session)
    preview = service.validate(service.read_file(output.getvalue(), "duplicate.xlsx"), portfolio_id)
    assert preview.file_duplicate_rows == [3]


def test_similar_rows_with_different_date_are_not_duplicates(
    session: Session, portfolio_id: int
) -> None:
    frame = pd.concat([sample_frame().iloc[:1]] * 2, ignore_index=True)
    frame.loc[1, "transaction_date"] = frame.loc[0, "transaction_date"] - timedelta(days=1)
    assert ImportService(session).validate(frame, portfolio_id).file_duplicate_rows == []


def test_similar_rows_with_different_quantity_are_not_duplicates(
    session: Session, portfolio_id: int
) -> None:
    frame = pd.concat([sample_frame().iloc[:1]] * 2, ignore_index=True)
    frame.loc[1, "quantity"] = 101
    assert ImportService(session).validate(frame, portfolio_id).file_duplicate_rows == []


def test_multiple_file_duplicates(session: Session, portfolio_id: int) -> None:
    frame = pd.concat([sample_frame().iloc[:1]] * 4, ignore_index=True)
    preview = ImportService(session).validate(frame, portfolio_id)
    assert preview.file_duplicate_rows == [3, 4, 5]


def test_execute_rejects_duplicates_without_authorization(
    session: Session, portfolio_id: int
) -> None:
    frame = pd.concat([sample_frame().iloc[:1]] * 2, ignore_index=True)
    preview = ImportService(session).validate(frame, portfolio_id)
    with pytest.raises(BusinessRuleError, match="sin autorización"):
        ImportService(session).execute(preview)
    assert TransactionRepository(session).list_for_portfolio(portfolio_id) == []
    assert "IMPORT_REJECTED" in list(session.scalars(select(AuditLogModel.action)))


def test_execute_accepts_duplicates_explicitly(
    session: Session, portfolio_id: int
) -> None:
    frame = pd.concat([sample_frame().iloc[:1]] * 2, ignore_index=True)
    service = ImportService(session)
    preview = service.validate(frame, portfolio_id)
    assert service.execute(preview, allow_duplicates=True) == 2
    actions = list(session.scalars(select(AuditLogModel.action)))
    assert "IMPORT_BATCH_WITH_DUPLICATES" in actions


def test_allowed_duplicates_still_roll_back_on_later_error(
    session: Session,
    portfolio_id: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.concat([sample_frame().iloc[:1]] * 3, ignore_index=True)
    service = ImportService(session)
    preview = service.validate(frame, portfolio_id)
    original = TransactionService.register
    calls = 0

    def fail_third(self, data, *, commit=True):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("fallo posterior")
        return original(self, data, commit=commit)

    monkeypatch.setattr(TransactionService, "register", fail_third)
    with pytest.raises(RuntimeError, match="fallo posterior"):
        service.execute(preview, allow_duplicates=True)
    assert TransactionRepository(session).list_for_portfolio(portfolio_id) == []


def test_simulation_stops_after_business_error(
    session: Session, portfolio_id: int
) -> None:
    frame = sample_frame()
    frame.loc[0, "quantity"] = 2_000_000
    preview = ImportService(session).validate(frame, portfolio_id)
    assert preview.simulation_complete is False
    assert preview.simulation_stopped_at_row == 2
    assert preview.not_simulated_rows == [3]


def test_import_date_outside_challenge_is_invalid(
    session: Session, portfolio_id: int
) -> None:
    portfolio = session.get(PortfolioModel, portfolio_id)
    assert portfolio is not None
    portfolio.challenge_start_date = date.today()
    session.commit()
    frame = sample_frame().iloc[:1].copy()
    frame.loc[0, "transaction_date"] = datetime.combine(
        portfolio.challenge_start_date - timedelta(days=1),
        datetime.min.time(),
        tzinfo=UTC,
    )
    preview = ImportService(session).validate(frame, portfolio_id)
    assert preview.errors
    assert preview.simulation_complete is False
    with pytest.raises(BusinessRuleError):
        ImportService(session).execute(preview)
    assert TransactionRepository(session).list_for_portfolio(portfolio_id) == []
