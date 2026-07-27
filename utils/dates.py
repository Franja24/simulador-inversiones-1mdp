"""Ayudas de fecha."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Devuelve la hora actual en UTC."""
    return datetime.now(UTC)

