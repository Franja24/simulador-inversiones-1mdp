"""Pruebas de normalización y antigüedad de precios."""

from datetime import UTC, datetime

import pytest

from utils.dates import is_stale_price


@pytest.mark.parametrize(
    ("last_update", "current_time", "expected"),
    [
        (datetime(2026, 7, 27, 9), datetime(2026, 7, 27, 18), False),
        (datetime(2026, 7, 27, 9), datetime(2026, 7, 28, 18), False),
        (datetime(2026, 7, 27, 9), datetime(2026, 7, 29, 18), True),
        (datetime(2026, 7, 24, 9), datetime(2026, 7, 27, 18), False),
        (datetime(2026, 7, 24, 9), datetime(2026, 7, 28, 18), True),
        (datetime(2026, 7, 29, 9), datetime(2026, 7, 28, 18), False),
        (
            datetime(2026, 7, 27, 9, tzinfo=UTC),
            datetime(2026, 7, 29, 18, tzinfo=UTC),
            True,
        ),
    ],
)
def test_stale_price_business_days(
    last_update: datetime, current_time: datetime, expected: bool
) -> None:
    assert is_stale_price(last_update, current_time) is expected


def test_stale_price_rejects_negative_allowance() -> None:
    with pytest.raises(ValueError):
        is_stale_price(datetime.now(UTC), datetime.now(UTC), -1)
