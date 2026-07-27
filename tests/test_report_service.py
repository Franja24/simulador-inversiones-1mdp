"""Pruebas del reporte Excel."""

from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy.orm import Session

from services.report_service import ReportService


def test_report_has_expected_sheets(
    session: Session, portfolio_id: int, tmp_path: Path
) -> None:
    path = ReportService(session).generate(portfolio_id, tmp_path)
    assert path.exists()
    workbook = load_workbook(path)
    assert workbook.sheetnames == ReportService.SHEETS
    for sheet in workbook.worksheets:
        assert sheet.freeze_panes == "A2"
        assert all(cell.font.bold for cell in sheet[1])
        assert sheet.auto_filter.ref is not None
    workbook.close()
