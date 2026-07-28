"""Pruebas offline y deterministas del AQS y backtesting."""

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from config.quant_score import BacktestConfig, QuantScoreConfig
from domain.market import MarketBar
from providers.yahoo_provider import YahooProvider
from repositories.market_history_repository import MarketHistoryRepository
from repositories.quant_repository import QuantRepository, QuantUniverseRepository
from services.backtest_service import BacktestService
from services.factor_normalization import normalize_factor, winsorize
from services.history_service import HistoryService
from services.market_regime_service import MarketRegimeService
from services.quant_report_service import QuantReportService
from services.quant_score_service import QuantScoreService


def trend_bars(
    symbol: str,
    start: date,
    count: int,
    *,
    drift: float,
    volatility: float = 0,
) -> list[MarketBar]:
    output: list[MarketBar] = []
    cursor = start
    index = 0
    while len(output) < count:
        if cursor.weekday() < 5:
            shock = volatility * ((index % 5) - 2)
            price = max(1.0, 100 + drift * index + shock)
            output.append(
                MarketBar(
                    symbol=symbol,
                    date=cursor,
                    open=price * 0.999,
                    high=price * 1.01,
                    low=price * 0.99,
                    close=price,
                    adj_close=price,
                    volume=1_000_000 + index * 10_000,
                    provider="test",
                )
            )
            index += 1
        cursor += timedelta(days=1)
    return output


def seed_quant_history(session: Session, count: int = 90) -> dict[str, list[MarketBar]]:
    data = {
        "ALFA.MX": trend_bars("ALFA.MX", date(2025, 1, 2), count, drift=1.0),
        "BETA.MX": trend_bars("BETA.MX", date(2025, 1, 2), count, drift=0.2),
        "GAMA.MX": trend_bars("GAMA.MX", date(2025, 1, 2), count, drift=-0.4),
        "^MXX": trend_bars("^MXX", date(2025, 1, 2), count, drift=0.3),
    }
    repository = MarketHistoryRepository(session)
    for rows in data.values():
        repository.upsert_many(rows)
    session.commit()
    return data


def test_config_weights_and_constraints() -> None:
    config = QuantScoreConfig()
    assert sum(config.weights.values()) == pytest.approx(1)
    with pytest.raises(ValidationError):
        QuantScoreConfig(momentum_20_weight=0.30)
    with pytest.raises(ValidationError):
        QuantScoreConfig(normalization_method="unknown")
    with pytest.raises(ValidationError):
        BacktestConfig(weighting="optimized")


def test_normalization_winsor_ties_inverse_and_methods() -> None:
    raw = pd.Series([1.0, 2.0, 3.0, 1000.0])
    clipped = winsorize(raw, 0.25, 0.75)
    assert clipped.max() < 1000
    percentile = normalize_factor(
        {"A": 1, "B": 2, "C": 2, "D": None}, lower=0, upper=1
    )
    assert percentile["B"] == percentile["C"]
    assert percentile["D"] is None
    inverse = normalize_factor(
        {"A": 1, "B": 2}, inverse=True, lower=0, upper=1
    )
    assert inverse["A"] > inverse["B"]  # type: ignore[operator]
    robust = normalize_factor(
        {"A": -10, "B": 0, "C": 10},
        method="robust_zscore",
        lower=0,
        upper=1,
    )
    assert robust["A"] < robust["B"] < robust["C"]  # type: ignore[operator]
    assert normalize_factor({"A": 1})["A"] == 50
    assert normalize_factor({"A": None})["A"] is None
    with pytest.raises(ValueError):
        normalize_factor({"A": 1}, method="bad")


def test_regimes_bull_bear_sideways_high_volatility_and_insufficient(
    session: Session,
) -> None:
    repository = MarketHistoryRepository(session)
    for rows in [
        trend_bars("BULL", date(2025, 1, 2), 80, drift=1),
        trend_bars("BEAR", date(2025, 1, 2), 80, drift=-0.8),
        trend_bars("SIDE", date(2025, 1, 2), 80, drift=0),
        trend_bars("VOL", date(2025, 1, 2), 80, drift=0.1, volatility=12),
    ]:
        repository.upsert_many(rows)
    session.commit()
    end = date(2025, 5, 30)
    service = MarketRegimeService(session)
    assert service.calculate("BULL", end).primary_regime == "BULLISH"
    assert service.calculate("BEAR", end).primary_regime == "BEARISH"
    assert service.calculate("SIDE", end).primary_regime == "SIDEWAYS"
    assert service.calculate("VOL", end).high_volatility is True
    assert service.calculate("NONE", end).primary_regime == "INSUFFICIENT_DATA"


def test_aqs_universe_explanation_persistence_versions_and_ranking(
    session: Session,
) -> None:
    data = seed_quant_history(session)
    effective = data["ALFA.MX"][-1].date
    service = QuantScoreService(session)
    config = QuantScoreConfig(minimum_history_rows=60)
    service.calculate_universe(
        ["GAMA.MX", "ALFA.MX", "BETA.MX"],
        data["ALFA.MX"][-2].date,
        "^MXX",
        config,
    )
    results = service.calculate_universe(
        ["GAMA.MX", "ALFA.MX", "BETA.MX", "^MXX"],
        effective,
        "^MXX",
        config,
    )
    assert len(results) == 3
    assert all(0 <= item.total_score <= 100 for item in results)
    assert all(0 <= item.confidence <= 100 for item in results)
    assert all(len(item.components) == 8 for item in results)
    ranking = service.rank_universe(results)
    assert [item.rank for item in ranking] == [1, 2, 3]
    assert any(item.score_change is not None for item in ranking)
    assert service.explain_score(results[0])
    saved = service.load_saved_result("ALFA.MX", effective, "aqs-1.0")
    assert saved is not None
    assert saved.total_score == next(
        item.total_score for item in results if item.symbol == "ALFA.MX"
    )
    one = service.calculate_symbol(
        "ALFA.MX", effective, "^MXX", config, universe=["ALFA.MX", "BETA.MX"]
    )
    assert one.symbol == "ALFA.MX"
    version = config.model_copy(update={"model_version": "aqs-test-2"})
    service.calculate_universe(["ALFA.MX", "BETA.MX"], effective, "^MXX", version)
    comparison = service.compare_versions(
        "ALFA.MX", effective, ["aqs-1.0", "aqs-test-2", "missing"]
    )
    assert comparison["aqs-1.0"] is not None
    assert comparison["missing"] is None
    forced = service.calculate_universe(
        ["ALFA.MX", "BETA.MX"], effective, "^MXX", config, force=True
    )
    assert forced
    assert QuantScoreService.classify(90) == "MUY_FUERTE"
    assert QuantScoreService.classify(72) == "FUERTE"
    assert QuantScoreService.classify(60) == "POSITIVA"
    assert QuantScoreService.classify(50) == "NEUTRAL"
    assert QuantScoreService.classify(35) == "DÉBIL"
    assert QuantScoreService.classify(10) == "MUY_DÉBIL"


def test_aqs_insufficient_data_and_universe_repository(session: Session) -> None:
    repository = QuantUniverseRepository(session)
    repository.save(" alfa.mx ", "Alfa", "Industrial")
    repository.save("BETA.MX", active=False)
    assert [item.symbol for item in repository.list_active()] == ["ALFA.MX"]
    session.commit()
    result = QuantScoreService(session).calculate_symbol(
        "VACIA.MX", date(2025, 1, 2), "^MXX"
    )
    assert result.confidence < 50
    assert result.warnings
    assert QuantScoreService(session).calculate_universe(
        ["^MXX"], date(2025, 1, 2), "^MXX", QuantScoreConfig()
    ) == []
    with pytest.raises(ValueError):
        QuantScoreService(session).calculate_symbol(
            "A", date(2025, 1, 2), "^MXX", universe=["^MXX"]
        )


def test_future_data_cannot_change_historical_score(session: Session) -> None:
    data = seed_quant_history(session, 75)
    cutoff = data["ALFA.MX"][60].date
    config = QuantScoreConfig(minimum_history_rows=20)
    service = QuantScoreService(session)
    before = service.calculate_universe(
        ["ALFA.MX", "BETA.MX", "GAMA.MX"], cutoff, "^MXX", config, force=True
    )
    future = data["GAMA.MX"][-1].model_copy(
        update={
            "open": 9_900,
            "high": 10_100,
            "low": 9_800,
            "close": 10_000,
            "adj_close": 10_000,
            "volume": 99_000_000,
        }
    )
    MarketHistoryRepository(session).upsert_many([future])
    session.commit()
    after = service.calculate_universe(
        ["ALFA.MX", "BETA.MX", "GAMA.MX"], cutoff, "^MXX", config, force=True
    )
    assert [
        (item.symbol, item.base_score, item.total_score) for item in before
    ] == [
        (item.symbol, item.base_score, item.total_score) for item in after
    ]


def test_backtest_d_plus_one_costs_benchmarks_walk_forward_and_determinism(
    session: Session, tmp_path: Path,
) -> None:
    data = seed_quant_history(session, 80)
    start = data["ALFA.MX"][45].date
    end = data["ALFA.MX"][-1].date
    score_config = QuantScoreConfig(minimum_history_rows=20)
    test_config = BacktestConfig(
        top_n=2,
        rebalance_frequency=10,
        holding_period=5,
        transaction_cost_bps=25,
        maximum_symbol_weight=0.5,
        calibration_sessions=20,
        evaluation_sessions=5,
    )
    service = BacktestService(session)
    first = service.run(
        ["ALFA.MX", "BETA.MX", "GAMA.MX"],
        start,
        end,
        "^MXX",
        score_config,
        test_config,
    )
    assert first.trades
    assert all(trade.execution_date > trade.signal_date for trade in first.trades)
    assert all(trade.net_return < trade.gross_return for trade in first.trades)
    assert set(first.comparison) == {
        "aqs",
        "benchmark",
        "equal_weight_universe",
        "random_selection",
        "momentum_20",
        "cash",
    }
    assert first.walk_forward_periods
    second = service.run(
        ["ALFA.MX", "BETA.MX", "GAMA.MX"],
        start,
        end,
        "^MXX",
        score_config,
        test_config,
    )
    assert second.run_id == first.run_id
    assert second.metrics == first.metrics
    assert QuantRepository(session).load_result(
        "ALFA.MX", first.trades[0].signal_date, "aqs-1.0"
    ) is not None
    current_scores = QuantScoreService(session).calculate_universe(
        ["ALFA.MX", "BETA.MX", "GAMA.MX"],
        end,
        "^MXX",
        score_config,
        force=True,
    )
    current_ranking = QuantScoreService(session).rank_universe(current_scores)
    reporter = QuantReportService()
    path = reporter.generate(current_ranking, current_scores, first, tmp_path)
    assert path.exists()
    assert b"ALFA" in reporter.ranking_csv(current_ranking)
    assert b"signal_date" in reporter.backtest_csv(first)
    assert b"backtest" in reporter.configuration_json(first)


def test_backtest_rejects_short_range_and_sensitivity(session: Session) -> None:
    data = seed_quant_history(session, 65)
    service = BacktestService(session)
    with pytest.raises(ValueError):
        service.run(
            ["ALFA.MX"],
            data["ALFA.MX"][0].date,
            data["ALFA.MX"][2].date,
            "^MXX",
        )
    scenarios = service.sensitivity(
        ["ALFA.MX", "BETA.MX", "GAMA.MX"],
        data["ALFA.MX"][45].date,
        data["ALFA.MX"][-1].date,
        "^MXX",
        QuantScoreConfig(minimum_history_rows=20),
        BacktestConfig(
            top_n=2,
            rebalance_frequency=10,
            holding_period=5,
            maximum_symbol_weight=0.5,
            calibration_sessions=20,
            evaluation_sessions=5,
        ),
    )
    assert len(scenarios) == 9
    assert all("fragile" in item for item in scenarios)


class EmptyTicker:
    def history(self, **kwargs):  # type: ignore[no-untyped-def]
        return pd.DataFrame()


class EmptyYahoo:
    __version__ = "test"

    @staticmethod
    def Ticker(symbol: str) -> EmptyTicker:
        return EmptyTicker()


def test_completely_empty_valid_range_is_marked_no_data(session: Session) -> None:
    provider = YahooProvider(EmptyYahoo())
    service = HistoryService(session, provider)
    start = date(2026, 1, 5)
    end = date(2026, 1, 7)
    assert service.update_symbol("VACIA.MX", start, end) == 0
    assert service.missing_dates("VACIA.MX", start, end) == []
    assert service.repository.known_no_data(
        "VACIA.MX", "yahoo", start, end
    ) == {start, date(2026, 1, 6), end}
