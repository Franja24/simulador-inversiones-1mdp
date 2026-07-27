"""Pruebas offline de consolidación de datos e indicadores."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from domain.market import MarketBar
from providers.yahoo_provider import YahooProvider
from repositories.market_history_repository import (
    IndicatorCacheRepository,
    MarketHistoryRepository,
)
from services.benchmark_service import BenchmarkService
from services.history_service import HistoryService
from services.indicator_service import IndicatorService
from services.market_calendar import WeekdayMarketCalendar
from services.market_session_service import BMVSessionService
from tests.test_market_intelligence import FakeYahoo, MockProvider, bars
from utils.market_money import market_price_to_decimal


def test_weekday_calendar_weekends_and_simulated_holiday() -> None:
    holiday = date(2026, 1, 6)
    calendar = WeekdayMarketCalendar({holiday})
    sessions = calendar.expected_sessions(date(2026, 1, 3), date(2026, 1, 7))
    assert date(2026, 1, 3) not in sessions
    assert date(2026, 1, 4) not in sessions
    assert holiday not in sessions
    assert sessions == {date(2026, 1, 5), date(2026, 1, 7)}


def test_no_data_is_not_requested_again_unless_forced(session: Session) -> None:
    all_bars = bars("AMXL.MX", date(2026, 1, 5), 5)
    available = [bar for bar in all_bars if bar.date != date(2026, 1, 7)]
    provider = MockProvider({"AMXL.MX": available})
    service = HistoryService(session, provider)
    assert service.update_symbol(
        "AMXL.MX", all_bars[0].date, all_bars[-1].date
    ) == 4
    assert len(provider.calls) == 1
    assert service.missing_dates(
        "AMXL.MX", all_bars[0].date, all_bars[-1].date
    ) == []
    assert service.update_symbol(
        "AMXL.MX", all_bars[0].date, all_bars[-1].date
    ) == 0
    assert len(provider.calls) == 1
    service.update_symbol(
        "AMXL.MX", all_bars[0].date, all_bars[-1].date, force=True
    )
    assert len(provider.calls) == 2


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (datetime(2026, 1, 5, 8, 29), False),
        (datetime(2026, 1, 5, 8, 30), True),
        (datetime(2026, 1, 5, 15, 0), True),
        (datetime(2026, 1, 5, 15, 1), False),
        (datetime(2026, 1, 3, 10, 0), False),
    ],
)
def test_bmv_session_with_injected_clock(
    current: datetime, expected: bool
) -> None:
    service = BMVSessionService(clock=lambda: current)
    assert service.is_open() is expected


def test_bmv_session_configurable_hours() -> None:
    service = BMVSessionService(
        clock=lambda: datetime(2026, 1, 5, 7, 30),
        open_time=time(7),
        close_time=time(8),
    )
    assert service.is_open() is True


def valid_bar_data() -> dict[str, object]:
    return {
        "symbol": " amxl.mx ",
        "date": date(2026, 1, 5),
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 11.0,
        "adj_close": 10.9,
        "volume": 100,
        "dividends": 0.0,
        "stock_splits": 0.0,
        "provider": "mock",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("open", 0),
        ("high", 0),
        ("low", 0),
        ("close", 0),
        ("adj_close", 0),
        ("volume", -1),
        ("dividends", -1),
        ("stock_splits", -1),
    ],
)
def test_market_bar_rejects_non_positive_fields(field: str, value: object) -> None:
    data = valid_bar_data()
    data[field] = value
    with pytest.raises(ValidationError):
        MarketBar.model_validate(data)


@pytest.mark.parametrize(
    "changes",
    [
        {"high": 8.0},
        {"high": 10.5, "close": 11.0},
        {"high": 10.5, "open": 11.0},
        {"low": 10.5, "open": 10.0},
        {"low": 11.5, "close": 11.0},
    ],
)
def test_market_bar_rejects_impossible_ohlc(changes: dict[str, object]) -> None:
    data = valid_bar_data()
    data.update(changes)
    with pytest.raises(ValidationError):
        MarketBar.model_validate(data)


def test_market_bar_normalizes_symbol_and_rejects_invalid_date() -> None:
    assert MarketBar.model_validate(valid_bar_data()).symbol == "AMXL.MX"
    data = valid_bar_data()
    data["date"] = "not-a-date"
    with pytest.raises(ValidationError):
        MarketBar.model_validate(data)


def test_batch_results_keep_partial_successes() -> None:
    data = bars("AMXL.MX", date(2026, 1, 5), 2)
    provider = MockProvider({"AMXL.MX": data})
    mixed = provider.get_multiple_quotes(["AMXL.MX", "INVALID", "AMXL.MX"])
    assert set(mixed.successes) == {"AMXL.MX"}
    assert set(mixed.errors) == {"INVALID"}
    invalid = provider.get_multiple_history(
        ["BAD1", "BAD2"], date(2026, 1, 5), date(2026, 1, 6)
    )
    assert invalid.successes == {}
    assert set(invalid.errors) == {"BAD1", "BAD2"}
    assert provider.get_multiple_quotes([]).successes == {}


class LeakyProvider(MockProvider):
    """Proveedor que ignora el rango para probar el filtro del servicio."""

    def get_history(self, symbol: str, start: date, end: date) -> list[MarketBar]:
        self.calls.append((symbol, start, end))
        return self.data[symbol]


def test_incremental_filters_out_of_range_duplicates_and_order(
    session: Session,
) -> None:
    expected = bars("AMXL.MX", date(2026, 1, 5), 3)
    outside_before = bars("AMXL.MX", date(2026, 1, 2), 1)[0]
    outside_after = bars("AMXL.MX", date(2026, 1, 8), 1)[0]
    provider = LeakyProvider(
        {
            "AMXL.MX": [
                outside_after,
                expected[2],
                expected[0],
                expected[1],
                expected[1],
                outside_before,
            ]
        }
    )
    service = HistoryService(session, provider)
    assert service.update_symbol(
        "AMXL.MX", expected[0].date, expected[-1].date
    ) == 3
    stored = service.load_history("AMXL.MX")
    assert list(stored["date"]) == [bar.date for bar in expected]


def test_incremental_extends_forward_and_backward(session: Session) -> None:
    data = bars("AMXL.MX", date(2026, 1, 2), 6)
    provider = MockProvider({"AMXL.MX": data})
    service = HistoryService(session, provider)
    assert service.update_symbol("AMXL.MX", data[1].date, data[3].date) == 3
    assert service.update_symbol("AMXL.MX", data[1].date, data[5].date) == 2
    assert service.update_symbol("AMXL.MX", data[0].date, data[5].date) == 1
    assert len(service.load_history("AMXL.MX")) == 6


def test_invalid_bar_rolls_back_and_logs_error(session: Session) -> None:
    invalid = MarketBar.model_construct(
        symbol="AMXL.MX",
        date=date(2026, 1, 5),
        open=10,
        high=8,
        low=9,
        close=11,
        adj_close=11,
        volume=100,
        dividends=0,
        stock_splits=0,
        provider="mock",
    )
    provider = MockProvider({"AMXL.MX": [invalid]})
    service = HistoryService(session, provider)
    with pytest.raises(ValidationError):
        service.update_symbol("AMXL.MX", invalid.date, invalid.date)
    assert service.load_history("AMXL.MX").empty
    assert MarketHistoryRepository(session).recent_errors()[0].symbol == "AMXL.MX"


def indicator_frame(closes: list[float]) -> pd.DataFrame:
    """Construye OHLC consistente a partir de cierres."""
    return pd.DataFrame(
        {
            "date": [
                date(2026, 1, 1) + timedelta(days=index)
                for index in range(len(closes))
            ],
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
            "adj_close": closes,
            "volume": [1000] * len(closes),
        }
    )


@pytest.mark.parametrize(
    ("closes", "expected"),
    [
        ([float(value) for value in range(1, 21)], 100.0),
        ([float(value) for value in range(21, 1, -1)], 0.0),
        ([10.0] * 20, 50.0),
    ],
)
def test_rsi_wilder_edge_cases(closes: list[float], expected: float) -> None:
    result = IndicatorService._calculate_frame(indicator_frame(closes))
    assert result.iloc[-1]["rsi_14"] == pytest.approx(expected)


def test_rsi_known_reference_and_insufficient_history() -> None:
    closes = [
        44.34,
        44.09,
        44.15,
        43.61,
        44.33,
        44.83,
        45.10,
        45.42,
        45.84,
        46.08,
        45.89,
        46.03,
        45.61,
        46.28,
        46.28,
    ]
    result = IndicatorService._calculate_frame(indicator_frame(closes))
    assert result.iloc[-1]["rsi_14"] == pytest.approx(70.464135, abs=1e-5)
    short = IndicatorService._calculate_frame(indicator_frame([10.0] * 13))
    assert short["rsi_14"].isna().all()


def test_atr_true_range_gap_reference() -> None:
    closes = [10.0] * 14
    frame = indicator_frame(closes)
    frame.loc[13, ["open", "high", "low", "close", "adj_close"]] = [
        14,
        15,
        13,
        14,
        14,
    ]
    result = IndicatorService._calculate_frame(frame)
    assert result.iloc[13]["atr_14"] == pytest.approx((13 * 2 + 5) / 14)


@pytest.mark.parametrize("direction", [1, -1])
def test_adx_wilder_trends(direction: int) -> None:
    closes = [100 + direction * index for index in range(40)]
    result = IndicatorService._calculate_frame(indicator_frame(closes))
    assert result.iloc[-1]["adx_14"] == pytest.approx(100.0)
    if direction > 0:
        assert result.iloc[-1]["plus_di_14"] > result.iloc[-1]["minus_di_14"]
    else:
        assert result.iloc[-1]["minus_di_14"] > result.iloc[-1]["plus_di_14"]


def test_adx_lateral_and_insufficient_are_safe() -> None:
    lateral = IndicatorService._calculate_frame(indicator_frame([10.0] * 40))
    assert lateral.iloc[-1]["adx_14"] == pytest.approx(0.0)
    assert pd.notna(lateral.iloc[-1]["adx_14"])
    short = IndicatorService._calculate_frame(indicator_frame([10.0] * 10))
    assert short["atr_14"].isna().all()
    assert short["adx_14"].isna().all()


def test_indicator_cache_invalidates_on_corrections_and_version(
    session: Session,
) -> None:
    data = bars("AMXL.MX", date(2025, 1, 2), 30)
    repository = MarketHistoryRepository(session)
    repository.upsert_many(data)
    session.commit()
    service = IndicatorService(session)
    first = service.calculate("AMXL.MX")
    cache = IndicatorCacheRepository(session).get("AMXL.MX")
    assert cache is not None
    initial_version = cache.history_version
    second = service.calculate("AMXL.MX")
    pd.testing.assert_frame_equal(second, first, check_dtype=False)

    corrected = data[10].model_copy(
        update={"close": data[10].close + 0.5, "volume": data[10].volume + 7}
    )
    repository.upsert_many([corrected])
    session.commit()
    service.calculate("AMXL.MX")
    corrected_cache = IndicatorCacheRepository(session).get("AMXL.MX")
    assert corrected_cache is not None
    assert corrected_cache.history_version != initial_version

    IndicatorService(session, indicator_version="test-v3").calculate("AMXL.MX")
    versioned = IndicatorCacheRepository(session).get("AMXL.MX")
    assert versioned is not None
    assert versioned.indicator_version == "test-v3"


class MultiIndexTicker:
    fast_info = FakeYahoo.Ticker("AMXL.MX").fast_info

    def history(self, **kwargs):  # type: ignore[no-untyped-def]
        index = pd.DatetimeIndex(["2026-01-05", "2026-01-06"], tz="UTC")
        columns = pd.MultiIndex.from_product(
            [
                ["Open", "High", "Low", "Close", "Adj Close", "Volume"],
                ["AMXL.MX"],
            ]
        )
        return pd.DataFrame(
            [
                [10, 12, 9, 11, 10.8, float("nan")],
                [float("nan"), 12, 9, 11, 10.9, 100],
            ],
            index=index,
            columns=columns,
        )


class MultiIndexYahoo:
    __version__ = "test"

    @staticmethod
    def Ticker(symbol: str) -> MultiIndexTicker:
        return MultiIndexTicker()


def test_yahoo_handles_multiindex_nan_and_missing_volume() -> None:
    provider = YahooProvider(MultiIndexYahoo(), max_workers=2)
    history = provider.get_history(
        "AMXL.MX", date(2026, 1, 5), date(2026, 1, 6)
    )
    assert len(history) == 1
    assert history[0].adj_close == 10.8
    assert history[0].volume == 0
    with pytest.raises(ValueError):
        YahooProvider(MultiIndexYahoo(), max_workers=0)


def test_yahoo_batch_partial_results() -> None:
    provider = YahooProvider(FakeYahoo(), max_workers=2)
    result = provider.get_multiple_quotes(["AMXL", "INVALID", "AMXL"])
    assert set(result.successes) == {"AMXL"}
    assert set(result.errors) == {"INVALID"}


def test_benchmark_alignment_and_empty_cache(session: Session) -> None:
    benchmark = bars("^MXX", date(2026, 1, 5), 3)
    market = bars("AMXL.MX", date(2026, 1, 6), 3)
    provider = MockProvider({"^MXX": benchmark, "AMXL.MX": market})
    service = BenchmarkService(session, provider)
    assert service.load("^MXX").empty
    service.update("^MXX", benchmark[0].date, benchmark[-1].date)
    service.history.update_symbol(
        "AMXL.MX", market[0].date, market[-1].date
    )
    aligned = service.align_with_symbol("^MXX", "AMXL.MX")
    assert list(aligned["date"]) == [date(2026, 1, 6), date(2026, 1, 7)]
    assert "benchmark_return" in aligned
    assert "market_return" in aligned


def test_float_decimal_boundary_precision() -> None:
    price = market_price_to_decimal(123.456789)
    quantity = Decimal("1000000.123456")
    value = price * quantity
    assert price == Decimal("123.456789")
    assert isinstance(value, Decimal)
    assert value == Decimal("123456804.241481342784")
    with pytest.raises(ValueError):
        market_price_to_decimal(0)
