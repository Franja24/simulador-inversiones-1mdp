"""Pruebas offline de la plataforma de inteligencia de mercado."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from domain.market import MarketBar, MarketQuote
from providers.cache_provider import CacheProvider
from providers.future_provider import FutureProvider
from providers.market_provider import MarketProvider, MarketProviderError
from providers.provider_factory import create_market_provider
from providers.yahoo_provider import YahooProvider, normalize_yahoo_symbol
from repositories.market_history_repository import (
    IndicatorCacheRepository,
    MarketHistoryRepository,
)
from services.benchmark_service import BenchmarkService
from services.data_quality_service import DataQualityService
from services.history_service import HistoryService
from services.indicator_service import IndicatorService
from services.market_overview_service import MarketOverviewService
from services.quant_score_service import QuantScoreInput, QuantScoreResult
from services.simulation_service import SimulationInput, SimulationResult


def bars(
    symbol: str,
    start: date,
    count: int,
    *,
    provider: str = "mock",
) -> list[MarketBar]:
    """Genera velas hábiles deterministas."""
    result: list[MarketBar] = []
    cursor = start
    index = 0
    while len(result) < count:
        if cursor.weekday() < 5:
            price = 100 + index
            result.append(
                MarketBar(
                    symbol=symbol,
                    date=cursor,
                    open=price - 1,
                    high=price + 2,
                    low=price - 2,
                    close=price,
                    adj_close=price,
                    volume=1_000 + index,
                    timezone="America/Mexico_City",
                    provider=provider,
                )
            )
            index += 1
        cursor += timedelta(days=1)
    return result


class MockProvider(MarketProvider):
    """Proveedor sin red para pruebas."""

    def __init__(self, data: dict[str, list[MarketBar]], market_open: bool = False) -> None:
        self.data = data
        self.market_open = market_open
        self.calls: list[tuple[str, date, date]] = []

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def provider_version(self) -> str:
        return "1.0"

    @property
    def supported_markets(self) -> tuple[str, ...]:
        return ("BMV",)

    def get_quote(self, symbol: str) -> MarketQuote:
        history = self.data[symbol]
        return MarketQuote(
            symbol=symbol,
            price=history[-1].close,
            previous_close=history[-2].close if len(history) > 1 else None,
            volume=history[-1].volume,
            timestamp=datetime.now(UTC),
            provider=self.provider_name,
        )

    def get_history(self, symbol: str, start: date, end: date) -> list[MarketBar]:
        self.calls.append((symbol, start, end))
        if symbol not in self.data:
            raise MarketProviderError(f"Símbolo inválido: {symbol}")
        return [item for item in self.data[symbol] if start <= item.date <= end]

    def is_market_open(self) -> bool:
        return self.market_open


def test_history_cache_and_incremental_update(session: Session) -> None:
    data = bars("AMXL.MX", date(2026, 1, 5), 5)
    provider = MockProvider({"AMXL.MX": data})
    service = HistoryService(session, provider)
    assert service.update_symbol("AMXL.MX", data[0].date, data[-1].date) == 5
    assert service.update_symbol("AMXL.MX", data[0].date, data[-1].date) == 0
    assert len(provider.calls) == 1
    assert service.last_available_date("AMXL.MX") == data[-1].date
    assert len(service.load_history("AMXL.MX")) == 5


def test_missing_dates_and_gaps(session: Session) -> None:
    data = bars("AMXL.MX", date(2026, 1, 5), 5)
    repository = MarketHistoryRepository(session)
    repository.upsert_many([data[0], data[2], data[4]])
    session.commit()
    service = HistoryService(session, MockProvider({"AMXL.MX": data}))
    assert service.missing_dates("AMXL.MX", data[0].date, data[-1].date) == [
        data[1].date,
        data[3].date,
    ]
    assert service.refresh_if_needed("AMXL.MX", data[0].date, data[-1].date) == 2


def test_duplicates_are_not_inserted(session: Session) -> None:
    data = bars("AMXL.MX", date(2026, 1, 5), 2)
    repository = MarketHistoryRepository(session)
    assert repository.upsert_many(data) == 2
    assert repository.upsert_many(data) == 0


def test_cache_provider_works_offline(session: Session) -> None:
    data = bars("AMXL.MX", date(2026, 1, 5), 2)
    repository = MarketHistoryRepository(session)
    repository.upsert_many(data)
    session.commit()
    provider = CacheProvider(repository)
    quote = provider.get_quote("AMXL.MX")
    assert quote.price == data[-1].close
    assert quote.previous_close == data[0].close
    assert len(provider.get_history("AMXL.MX", data[0].date, data[-1].date)) == 2
    assert provider.is_market_open() is False
    with pytest.raises(MarketProviderError):
        provider.get_quote("INVALID.MX")


def test_indicator_calculation_and_cache(session: Session) -> None:
    data = bars("AMXL.MX", date(2025, 1, 2), 260)
    repository = MarketHistoryRepository(session)
    repository.upsert_many(data)
    session.commit()
    service = IndicatorService(session)
    result = service.calculate("AMXL.MX")
    expected = {
        "sma_200",
        "ema_9",
        "rsi_14",
        "macd",
        "macd_signal",
        "macd_histogram",
        "atr_14",
        "bollinger_upper",
        "adx_14",
        "roc_10",
        "momentum_10",
        "daily_return",
        "weekly_return",
        "monthly_return",
        "rolling_volatility_20",
        "average_volume_20",
        "relative_volume",
        "high_52_week",
        "low_52_week",
        "distance_to_high",
        "distance_to_low",
    }
    assert expected.issubset(result.columns)
    cached = IndicatorCacheRepository(session).get("AMXL.MX")
    assert cached is not None
    assert cached.last_history_date == data[-1].date
    second = service.calculate("AMXL.MX")
    assert len(second) == len(result)
    assert service.calculate("UNKNOWN.MX").empty


def test_benchmark_returns(session: Session) -> None:
    data = bars("^MXX", date(2026, 1, 5), 3)
    provider = MockProvider({"^MXX": data})
    service = BenchmarkService(session, provider)
    assert service.update("^MXX", data[0].date, data[-1].date) == 3
    frame = service.load("^MXX")
    assert "benchmark_return" in frame
    assert pd.isna(frame.iloc[0]["benchmark_return"])


def test_data_quality_detects_problems() -> None:
    frame = pd.DataFrame(
        [
            {"date": date(2026, 1, 6), "close": 100.0, "volume": 10},
            {"date": date(2026, 1, 5), "close": -1.0, "volume": -5},
            {"date": date(2026, 1, 5), "close": None, "volume": 10},
        ]
    )
    codes = {issue.code for issue in DataQualityService().inspect(frame)}
    assert {
        "DUPLICATE_DATE",
        "OUT_OF_ORDER",
        "NAN",
        "NEGATIVE_VOLUME",
        "INVALID_CLOSE",
        "EXTREME_OUTLIER",
    }.issubset(codes)
    assert DataQualityService().inspect(pd.DataFrame())[0].code == "EMPTY"


def test_market_overview_open_and_closed(session: Session) -> None:
    data = bars("AMXL.MX", date(2026, 1, 5), 2)
    repository = MarketHistoryRepository(session)
    repository.upsert_many(data)
    repository.save_sync("AMXL.MX", "mock", "OK", 2)
    session.commit()
    open_summary = MarketOverviewService(
        session, MockProvider({"AMXL.MX": data}, True)
    ).summary()
    closed_summary = MarketOverviewService(
        session, MockProvider({"AMXL.MX": data}, False)
    ).summary()
    assert open_summary["market_open"] is True
    assert closed_summary["market_open"] is False
    assert len(
        MarketOverviewService(session, MockProvider({"AMXL.MX": data})).symbol_table()
    ) == 1


class FakeTicker:
    """Ticker yfinance determinista."""

    fast_info = {
        "last_price": 18.5,
        "previous_close": 18.0,
        "last_volume": 1234,
        "timezone": "America/Mexico_City",
    }

    def history(self, **kwargs):  # type: ignore[no-untyped-def]
        index = pd.DatetimeIndex(
            ["2026-01-05", "2026-01-06"], tz="America/Mexico_City"
        )
        return pd.DataFrame(
            {
                "Open": [18.0, 18.2],
                "High": [18.8, 19.0],
                "Low": [17.9, 18.1],
                "Close": [18.5, 18.7],
                "Adj Close": [18.4, 18.6],
                "Volume": [1000, 1200],
                "Dividends": [0.1, 0.0],
                "Stock Splits": [0.0, 0.0],
            },
            index=index,
        )


class FakeYahoo:
    __version__ = "test"

    @staticmethod
    def Ticker(symbol: str) -> FakeTicker:
        if symbol == "INVALID.MX":
            raise ValueError("invalid")
        return FakeTicker()


def test_yahoo_provider_with_fake_client() -> None:
    provider = YahooProvider(FakeYahoo())
    quote = provider.get_quote("amxl")
    assert quote.symbol == "AMXL.MX"
    assert quote.price == 18.5
    history = provider.get_history(
        "AMXL", date(2026, 1, 5), date(2026, 1, 6)
    )
    assert len(history) == 2
    assert history[0].adj_close == 18.4
    assert history[0].dividends == 0.1
    assert history[0].timezone == "America/Mexico_City"
    assert provider.provider_version == "test"
    assert "BMV" in provider.supported_markets
    assert len(provider.get_multiple_quotes(["AMXL", "WALMEX"])) == 2
    assert len(
        provider.get_multiple_history(
            ["AMXL", "WALMEX"], date(2026, 1, 5), date(2026, 1, 6)
        )
    ) == 2


def test_yahoo_invalid_symbols_and_future_provider() -> None:
    assert normalize_yahoo_symbol("^MXX") == "^MXX"
    assert normalize_yahoo_symbol("AMXL.MX") == "AMXL.MX"
    with pytest.raises(ValueError):
        normalize_yahoo_symbol(" ")
    provider = YahooProvider(FakeYahoo())
    with pytest.raises(MarketProviderError):
        provider.get_quote("INVALID")
    future = FutureProvider()
    assert future.is_market_open() is False
    with pytest.raises(MarketProviderError):
        future.get_quote("AMXL.MX")
    with pytest.raises(MarketProviderError):
        future.get_history("AMXL.MX", date.today(), date.today())


def test_provider_factory_and_future_dtos(session: Session) -> None:
    assert create_market_provider("cache", session).provider_name == "cache"
    assert create_market_provider("future", session).provider_name == "future"
    with pytest.raises(ValueError, match="no soportado"):
        create_market_provider("unknown", session)
    quant_input = QuantScoreInput(symbol="AMXL.MX", metrics={"rsi": 50.0})
    quant_result = QuantScoreResult(
        symbol=quant_input.symbol,
        score=50,
        components={"technical": 50},
        methodology_version="future",
    )
    simulation_input = SimulationInput(symbol="AMXL.MX", horizon_days=30, paths=100)
    simulation_result = SimulationResult(
        symbol=simulation_input.symbol,
        horizon_days=30,
        paths=100,
        percentiles={"p50": 0.0},
        methodology_version="future",
    )
    assert quant_result.score == 50
    assert simulation_result.paths == 100
