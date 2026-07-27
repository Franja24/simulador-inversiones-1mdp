"""Pruebas de funciones financieras puras."""

from decimal import Decimal

from utils.calculations import maximum_drawdown, percentage_change


def test_percentage_change() -> None:
    assert percentage_change(Decimal("120"), Decimal("100")) == Decimal("20")
    assert percentage_change(Decimal("1"), Decimal("0")) == Decimal("0")


def test_maximum_drawdown() -> None:
    values = [Decimal("100"), Decimal("120"), Decimal("90"), Decimal("110")]
    assert maximum_drawdown(values) == Decimal("-25")
    assert maximum_drawdown([]) == Decimal("0")

