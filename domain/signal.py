"""Tipos reservados para señales informativas de fases posteriores."""

from enum import StrEnum


class SignalType(StrEnum):
    """Catálogo de señales admitidas por el diseño."""

    BUY_WATCH = "BUY_WATCH"
    MOMENTUM = "MOMENTUM"
    BREAKOUT = "BREAKOUT"
    OVERSOLD = "OVERSOLD"
    OVERBOUGHT = "OVERBOUGHT"
    STOP_LOSS_ALERT = "STOP_LOSS_ALERT"
    TAKE_PROFIT_ALERT = "TAKE_PROFIT_ALERT"
    HOLD = "HOLD"
    EXIT_WATCH = "EXIT_WATCH"
