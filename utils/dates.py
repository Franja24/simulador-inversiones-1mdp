"""Ayudas de fecha y días hábiles."""

from datetime import UTC, datetime, timedelta


def utc_now() -> datetime:
    """Devuelve la hora actual en UTC."""
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Normaliza fechas aware/naive; las naive se interpretan como UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def is_stale_price(
    last_update: datetime,
    current_time: datetime,
    allowed_business_days: int = 1,
) -> bool:
    """Indica si pasaron más días hábiles completos de los permitidos.

    Considera lunes a viernes y todavía no descuenta festivos de la BMV.
    Una fecha futura nunca se considera desactualizada.
    """
    if allowed_business_days < 0:
        raise ValueError("Los días hábiles permitidos no pueden ser negativos.")
    start = as_utc(last_update)
    current = as_utc(current_time)
    if start >= current:
        return False
    cursor = start.date() + timedelta(days=1)
    completed = 0
    while cursor <= current.date():
        if cursor.weekday() < 5:
            completed += 1
        cursor += timedelta(days=1)
    return completed > allowed_business_days
