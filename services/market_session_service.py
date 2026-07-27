"""Estado estimado de la sesión BMV con reloj inyectable."""

from collections.abc import Callable
from datetime import datetime, time
from zoneinfo import ZoneInfo

from services.market_calendar import MarketCalendar, WeekdayMarketCalendar


class BMVSessionService:
    """Evalúa una sesión simple sin festivos ni cierres extraordinarios."""

    DISCLAIMER = "Estado estimado; no contempla festivos ni cierres extraordinarios"

    def __init__(
        self,
        calendar: MarketCalendar | None = None,
        clock: Callable[[], datetime] | None = None,
        open_time: time = time(8, 30),
        close_time: time = time(15, 0),
    ) -> None:
        self.calendar = calendar or WeekdayMarketCalendar()
        self.clock = clock or (
            lambda: datetime.now(ZoneInfo("America/Mexico_City"))
        )
        self.open_time = open_time
        self.close_time = close_time

    def is_open(self) -> bool:
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo("America/Mexico_City"))
        else:
            now = now.astimezone(ZoneInfo("America/Mexico_City"))
        is_session = now.date() in self.calendar.expected_sessions(
            now.date(), now.date()
        )
        return is_session and self.open_time <= now.time() <= self.close_time
