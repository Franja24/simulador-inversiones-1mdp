"""Horizontes compatibles con las sesiones restantes del reto."""

from datetime import date

from services.market_calendar import MarketCalendar, WeekdayMarketCalendar


class ChallengeHorizonService:
    def __init__(self, calendar: MarketCalendar | None = None) -> None:
        self.calendar = calendar or WeekdayMarketCalendar()

    def remaining_sessions(self, current: date, challenge_end: date) -> int:
        if current > challenge_end:
            return 0
        return len(self.calendar.expected_sessions(current, challenge_end))

    def recommended_horizons(self, remaining_sessions: int) -> tuple[list[int], list[str]]:
        if remaining_sessions <= 0:
            return [], ["El reto ya terminó."]
        if remaining_sessions > 15:
            return [5, 10, 15], []
        if remaining_sessions > 5:
            return [remaining_sessions], ["Horizonte ajustado al tiempo restante."]
        return [remaining_sessions], [
            "Quedan cinco sesiones o menos; incertidumbre elevada."
        ]
