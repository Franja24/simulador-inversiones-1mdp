"""Backtesting y walk-forward OOS sin posiciones solapadas ni lookahead."""

import hashlib
import json
import math
import random
from datetime import UTC, date, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.quant_score import BacktestConfig, QuantScoreConfig
from database.models import MarketHistoryModel
from domain.quant import (
    BacktestMetrics,
    BacktestResult,
    BacktestTrade,
    WalkForwardMetrics,
    WalkForwardResult,
    WalkForwardWindowResult,
)
from repositories.quant_repository import QuantRepository
from services.allocation_service import RestrictedEqualWeightAllocator
from services.quant_score_service import QuantScoreService


class BacktestService:
    """Evalúa rankings con señal al cierre D y ejecución desde D+1."""

    EXECUTION_POLICY = "Señal cierre D; entrada apertura D+1 o posterior disponible."
    BIAS_WARNINGS = [
        "Backtest completo no equivale a validación fuera de muestra.",
        "El universo provisto puede contener sesgo de supervivencia.",
        "No se optimizan pesos usando el periodo evaluado.",
        "No se permiten posiciones solapadas.",
        "Los costos se descuentan en entrada y salida.",
    ]

    def __init__(self, session: Session) -> None:
        self.session = session
        self.scores = QuantScoreService(session)
        self.repository = QuantRepository(session)
        self.allocator = RestrictedEqualWeightAllocator()

    def run(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        benchmark_symbol: str,
        score_config: QuantScoreConfig | None = None,
        backtest_config: BacktestConfig | None = None,
    ) -> BacktestResult:
        score_cfg = QuantScoreConfig.model_validate(
            (score_config or QuantScoreConfig()).model_dump()
        )
        test_cfg = BacktestConfig.model_validate(
            (backtest_config or BacktestConfig()).model_dump()
        )
        universe = sorted({item.strip().upper() for item in symbols if item.strip()})
        sessions = self._sessions(universe, start_date, end_date)
        if len(sessions) <= test_cfg.holding_period + 1:
            raise ValueError("El rango no contiene sesiones suficientes.")
        rebalance_indices = range(
            0,
            len(sessions) - test_cfg.holding_period - 1,
            test_cfg.rebalance_frequency,
        )
        strategy_periods: dict[str, list[tuple[date, float]]] = {
            "aqs": [],
            "equal_weight_universe": [],
            "random_selection": [],
            "momentum_20": [],
        }
        benchmark_returns: list[tuple[date, float]] = []
        trades: list[BacktestTrade] = []
        warnings = list(self.BIAS_WARNINGS)
        rng = random.Random(test_cfg.random_seed)
        previous_weights: dict[str, float] = {}
        previous_cash = 1.0
        turnover = 0.0
        for index in rebalance_indices:
            signal_date = sessions[index]
            execution_date = sessions[index + 1]
            exit_date = sessions[index + 1 + test_cfg.holding_period]
            results = self.scores.calculate_universe(
                universe, signal_date, benchmark_symbol, score_cfg, force=True
            )
            ranking = self.scores.rank_universe(
                results, minimum_confidence=test_cfg.minimum_confidence
            )
            aqs_symbols = [item.symbol for item in ranking[: test_cfg.top_n]]
            momentum_symbols = [
                item.symbol
                for item in sorted(
                    results,
                    key=lambda item: (
                        -next(
                            (
                                component.raw_value
                                if component.raw_value is not None
                                else float("-inf")
                                for component in item.components
                                if component.name == "momentum_20"
                            ),
                            float("-inf"),
                        ),
                        item.symbol,
                    ),
                )[: test_cfg.top_n]
            ]
            random_symbols = rng.sample(
                universe, min(test_cfg.top_n, len(universe))
            )
            selections = {
                "aqs": aqs_symbols,
                "equal_weight_universe": universe,
                "random_selection": random_symbols,
                "momentum_20": momentum_symbols,
            }
            for name, selection in selections.items():
                period_return, period_trades, weights, cash, period_warnings = (
                    self._value_selection(
                        selection,
                        signal_date,
                        execution_date,
                        exit_date,
                        end_date,
                        test_cfg,
                        top_n=(
                            len(universe)
                            if name == "equal_weight_universe"
                            else test_cfg.top_n
                        ),
                    )
                )
                strategy_periods[name].append((exit_date, period_return))
                warnings.extend(f"{name}: {item}" for item in period_warnings)
                if name == "aqs":
                    trades.extend(period_trades)
                    turnover += self._turnover(
                        previous_weights, previous_cash, weights, cash
                    )
                    previous_weights, previous_cash = weights, cash
            benchmark_value = self._symbol_return(
                benchmark_symbol, execution_date, exit_date, end_date
            )
            if benchmark_value is None:
                warnings.append(
                    f"Benchmark sin entrada/salida válida para {signal_date}."
                )
                benchmark_value = 0.0
            benchmark_returns.append((exit_date, benchmark_value))
        aqs_periods = strategy_periods["aqs"]
        returns_series = pd.Series([item[1] for item in aqs_periods], dtype=float)
        benchmark_series = pd.Series(
            [item[1] for item in benchmark_returns], dtype=float
        )
        metrics = self._metrics(
            returns_series, benchmark_series, trades, turnover=turnover
        )
        audit = self._audit(
            universe, start_date, end_date, benchmark_symbol, score_cfg, test_cfg
        )
        result = BacktestResult(
            run_id=self._stable_id(audit),
            generated_at=datetime.now(UTC),
            model_version=score_cfg.model_version,
            start_date=start_date,
            end_date=end_date,
            benchmark_symbol=benchmark_symbol.upper(),
            equity_curve=self._curve(aqs_periods),
            benchmark_curve=self._curve(benchmark_returns),
            trades=trades,
            metrics=metrics,
            comparison={
                name: self._compound([item[1] for item in periods])
                for name, periods in strategy_periods.items()
            }
            | {
                "benchmark": metrics.benchmark_return or 0.0,
                "cash": 0.0,
            },
            walk_forward_periods=self.walk_forward_periods(
                sessions,
                test_cfg.calibration_sessions,
                test_cfg.evaluation_sessions,
            ),
            warnings=list(dict.fromkeys(warnings)),
            configuration={
                "score": score_cfg.model_dump(),
                "backtest": test_cfg.model_dump(),
                "universe": universe,
                "audit": audit,
            },
        )
        self.repository.save_backtest(result)
        self.session.commit()
        return result

    def run_walk_forward(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        benchmark_symbol: str,
        score_config: QuantScoreConfig,
        backtest_config: BacktestConfig,
    ) -> WalkForwardResult:
        universe = sorted({item.strip().upper() for item in symbols if item.strip()})
        sessions = self._sessions(universe, start_date, end_date)
        definitions = self._window_definitions(
            sessions,
            backtest_config.calibration_sessions,
            backtest_config.evaluation_sessions,
        )
        if not definitions:
            raise ValueError("No existen sesiones suficientes para walk-forward.")
        if backtest_config.evaluation_sessions <= backtest_config.holding_period + 1:
            raise ValueError(
                "Cada ventana de evaluación debe exceder holding_period + 1."
            )
        windows: list[WalkForwardWindowResult] = []
        for number, definition in enumerate(definitions, 1):
            frozen_score = QuantScoreConfig.model_validate(
                score_config.model_dump()
            )
            frozen_backtest = BacktestConfig.model_validate(
                backtest_config.model_dump()
            )
            evaluation = self.run(
                universe,
                definition["evaluation_start"],
                definition["evaluation_end"],
                benchmark_symbol,
                frozen_score,
                frozen_backtest,
            )
            windows.append(
                WalkForwardWindowResult(
                    window=number,
                    training_start=definition["training_start"],
                    training_end=definition["training_end"],
                    evaluation_start=definition["evaluation_start"],
                    evaluation_end=definition["evaluation_end"],
                    cumulative_return=evaluation.metrics.cumulative_return,
                    benchmark_return=evaluation.metrics.benchmark_return or 0.0,
                    max_drawdown=evaluation.metrics.max_drawdown,
                    sharpe=evaluation.metrics.sharpe,
                    sortino=evaluation.metrics.sortino,
                    trades=evaluation.trades,
                    equity_curve=evaluation.equity_curve,
                    benchmark_curve=evaluation.benchmark_curve,
                    frozen_configuration=evaluation.configuration,
                    warnings=evaluation.warnings,
                )
            )
        oos_curve = self._concatenate_curves(
            [item.equity_curve for item in windows]
        )
        benchmark_curve = self._concatenate_curves(
            [item.benchmark_curve for item in windows]
        )
        window_returns = [item.cumulative_return for item in windows]
        benchmark_window_returns = [item.benchmark_return for item in windows]
        aggregate = self._compound(window_returns)
        aggregate_benchmark = self._compound(benchmark_window_returns)
        dispersion = float(pd.Series(window_returns).std(ddof=0))
        mean_return = float(pd.Series(window_returns).mean())
        audit = self._audit(
            universe,
            start_date,
            end_date,
            benchmark_symbol,
            score_config,
            backtest_config,
        )
        audit["validation"] = "walk_forward_oos"
        result = WalkForwardResult(
            run_id=self._stable_id(audit),
            generated_at=datetime.now(UTC),
            model_version=score_config.model_version,
            start_date=start_date,
            end_date=end_date,
            benchmark_symbol=benchmark_symbol.upper(),
            windows=windows,
            oos_equity_curve=oos_curve,
            oos_benchmark_curve=benchmark_curve,
            oos_trades=[trade for window in windows for trade in window.trades],
            metrics=WalkForwardMetrics(
                aggregate_oos_return=aggregate,
                aggregate_benchmark_return=aggregate_benchmark,
                mean_window_return=mean_return,
                median_window_return=float(pd.Series(window_returns).median()),
                best_window_return=max(window_returns),
                worst_window_return=min(window_returns),
                benchmark_win_rate=sum(
                    value > benchmark
                    for value, benchmark in zip(
                        window_returns, benchmark_window_returns, strict=True
                    )
                )
                / len(windows),
                dispersion=dispersion,
                stability=(
                    "ESTABLE"
                    if dispersion <= max(0.01, abs(mean_return))
                    else "FRÁGIL"
                ),
                max_drawdown=self._curve_drawdown(oos_curve),
            ),
            audit=audit,
            warnings=[
                "La curva contiene exclusivamente periodos de evaluación OOS.",
                "Los pesos permanecen fijos; no hubo calibración con evaluación.",
                *self.BIAS_WARNINGS,
            ],
        )
        self.repository.save_walk_forward(result)
        self.session.commit()
        return result

    def sensitivity(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        benchmark_symbol: str,
        score_config: QuantScoreConfig,
        backtest_config: BacktestConfig,
    ) -> list[dict[str, float | str | bool]]:
        scenarios: list[tuple[str, QuantScoreConfig, BacktestConfig]] = [
            ("base", score_config, backtest_config),
            (
                "top_n_-1",
                score_config,
                backtest_config.model_copy(
                    update={"top_n": max(1, backtest_config.top_n - 1)}
                ),
            ),
            (
                "top_n_+1",
                score_config,
                backtest_config.model_copy(
                    update={"top_n": backtest_config.top_n + 1}
                ),
            ),
            (
                "costos_+20%",
                score_config,
                backtest_config.model_copy(
                    update={
                        "transaction_cost_bps":
                        backtest_config.transaction_cost_bps * 1.2
                    }
                ),
            ),
            (
                "frecuencia_+20%",
                score_config,
                backtest_config.model_copy(
                    update={
                        "rebalance_frequency": max(
                            backtest_config.holding_period,
                            round(backtest_config.rebalance_frequency * 1.2),
                        )
                    }
                ),
            ),
            (
                "horizonte_+1",
                score_config,
                backtest_config.model_copy(
                    update={
                        "holding_period": backtest_config.holding_period + 1,
                        "rebalance_frequency": max(
                            backtest_config.rebalance_frequency,
                            backtest_config.holding_period + 1,
                        ),
                    }
                ),
            ),
            (
                "confianza_+10",
                score_config,
                backtest_config.model_copy(
                    update={
                        "minimum_confidence": min(
                            100, backtest_config.minimum_confidence + 10
                        )
                    }
                ),
            ),
            (
                "momentum20_+20%",
                self._weight_variant(score_config, 1.2, "sens-plus"),
                backtest_config,
            ),
            (
                "momentum20_-20%",
                self._weight_variant(score_config, 0.8, "sens-minus"),
                backtest_config,
            ),
        ]
        output: list[dict[str, float | str | bool]] = []
        for name, scenario_score, scenario_backtest in scenarios:
            result = self.run(
                symbols,
                start_date,
                end_date,
                benchmark_symbol,
                scenario_score,
                scenario_backtest,
            )
            output.append(
                {
                    "scenario": name,
                    "cumulative_return": result.metrics.cumulative_return,
                    "max_drawdown": result.metrics.max_drawdown,
                    "fragile": False,
                }
            )
        values = [float(item["cumulative_return"]) for item in output]
        fragile = max(values) - min(values) > 0.20 if values else False
        for item in output:
            item["fragile"] = fragile
        return output

    def _value_selection(
        self,
        symbols: list[str],
        signal_date: date,
        execution_date: date,
        exit_date: date,
        maximum_date: date,
        config: BacktestConfig,
        *,
        top_n: int,
    ) -> tuple[
        float, list[BacktestTrade], dict[str, float], float, list[str]
    ]:
        prices = {
            symbol: self._execution_prices(
                symbol, execution_date, exit_date, maximum_date
            )
            for symbol in symbols
        }
        eligible = [symbol for symbol in symbols if prices[symbol] is not None]
        allocation = self.allocator.allocate(
            eligible,
            top_n=top_n,
            maximum_symbol_weight=config.maximum_symbol_weight,
            allow_cash=config.allow_cash,
        )
        period_return = 0.0
        trades: list[BacktestTrade] = []
        cost = config.transaction_cost_bps / 10_000 * 2
        for symbol, weight in allocation.weights.items():
            values = prices[symbol]
            if values is None:
                continue
            entry, exit_price, actual_execution, actual_exit = values
            gross = exit_price / entry - 1
            net = max(-1.0, gross - cost)
            period_return += weight * net
            trades.append(
                BacktestTrade(
                    signal_date=signal_date,
                    execution_date=actual_execution,
                    exit_date=actual_exit,
                    symbol=symbol,
                    entry_price=entry,
                    exit_price=exit_price,
                    gross_return=gross,
                    net_return=net,
                    weight=weight,
                    transaction_cost=cost,
                )
            )
        missing = [symbol for symbol in symbols if prices[symbol] is None]
        warnings = list(allocation.warnings)
        if missing:
            warnings.append(
                "Sin entrada/salida dentro del límite: " + ", ".join(missing)
            )
        return (
            period_return,
            trades,
            allocation.weights,
            allocation.cash_weight,
            warnings,
        )

    def _execution_prices(
        self,
        symbol: str,
        execution: date,
        exit_date: date,
        maximum_date: date,
    ) -> tuple[float, float, date, date] | None:
        if execution > maximum_date or exit_date > maximum_date:
            return None
        entry = self.session.scalar(
            select(MarketHistoryModel)
            .where(
                MarketHistoryModel.symbol == symbol.upper(),
                MarketHistoryModel.date >= execution,
                MarketHistoryModel.date <= maximum_date,
            )
            .order_by(MarketHistoryModel.date)
            .limit(1)
        )
        exit_bar = self.session.scalar(
            select(MarketHistoryModel)
            .where(
                MarketHistoryModel.symbol == symbol.upper(),
                MarketHistoryModel.date >= exit_date,
                MarketHistoryModel.date <= maximum_date,
            )
            .order_by(MarketHistoryModel.date)
            .limit(1)
        )
        if entry is None or exit_bar is None or exit_bar.date <= entry.date:
            return None
        return entry.open, exit_bar.close, entry.date, exit_bar.date

    def _symbol_return(
        self, symbol: str, start: date, end: date, maximum_date: date
    ) -> float | None:
        prices = self._execution_prices(symbol, start, end, maximum_date)
        return prices[1] / prices[0] - 1 if prices else None

    def _audit(
        self,
        universe: list[str],
        start_date: date,
        end_date: date,
        benchmark_symbol: str,
        score_config: QuantScoreConfig,
        backtest_config: BacktestConfig,
    ) -> dict[str, object]:
        return {
            "universe_hash": hashlib.sha256(
                "|".join(universe).encode()
            ).hexdigest(),
            "history_signature": self._history_signature(
                [*universe, benchmark_symbol.upper()], end_date
            ),
            "aqs_version": score_config.model_version,
            "score_config": score_config.model_dump(),
            "backtest_config": backtest_config.model_dump(),
            "seed": backtest_config.random_seed,
            "range": [start_date.isoformat(), end_date.isoformat()],
            "benchmark": benchmark_symbol.upper(),
            "execution_policy": self.EXECUTION_POLICY,
            "transaction_cost_bps": backtest_config.transaction_cost_bps,
            "constraints": {
                "top_n": backtest_config.top_n,
                "allow_cash": backtest_config.allow_cash,
                "maximum_symbol_weight": backtest_config.maximum_symbol_weight,
                "non_overlapping": True,
            },
        }

    def _history_signature(self, symbols: list[str], maximum_date: date) -> str:
        rows = self.session.scalars(
            select(MarketHistoryModel)
            .where(
                MarketHistoryModel.symbol.in_(symbols),
                MarketHistoryModel.date <= maximum_date,
            )
            .order_by(MarketHistoryModel.symbol, MarketHistoryModel.date)
        )
        digest = hashlib.sha256()
        for row in rows:
            digest.update(
                (
                    f"{row.symbol}|{row.date}|{row.open}|{row.high}|{row.low}|"
                    f"{row.close}|{row.adj_close}|{row.volume};"
                ).encode()
            )
        return digest.hexdigest()

    @staticmethod
    def _stable_id(audit: dict[str, object]) -> str:
        material = json.dumps(audit, sort_keys=True, default=str)
        return hashlib.sha256(material.encode()).hexdigest()[:24]

    @staticmethod
    def _turnover(
        previous: dict[str, float],
        previous_cash: float,
        current: dict[str, float],
        current_cash: float,
    ) -> float:
        symbols = set(previous) | set(current)
        gross_change = sum(
            abs(current.get(symbol, 0) - previous.get(symbol, 0))
            for symbol in symbols
        )
        return (gross_change + abs(current_cash - previous_cash)) / 2

    @staticmethod
    def _weight_variant(
        config: QuantScoreConfig, multiplier: float, suffix: str
    ) -> QuantScoreConfig:
        original = config.momentum_20_weight
        target = original * multiplier
        scale = (1 - target) / (1 - original)
        updates: dict[str, object] = {
            "model_version": f"{config.model_version}-{suffix}",
            "momentum_20_weight": target,
        }
        for name, weight in config.weights.items():
            if name != "momentum_20":
                updates[f"{name}_weight"] = weight * scale
        return config.model_copy(update=updates)

    @classmethod
    def walk_forward_periods(
        cls, sessions: list[date], calibration: int, evaluation: int
    ) -> list[dict[str, str | float]]:
        return [
            {
                "training_start": item["training_start"].isoformat(),
                "training_end": item["training_end"].isoformat(),
                "evaluation_start": item["evaluation_start"].isoformat(),
                "evaluation_end": item["evaluation_end"].isoformat(),
                "weights_calibrated": 0.0,
            }
            for item in cls._window_definitions(sessions, calibration, evaluation)
        ]

    @staticmethod
    def _window_definitions(
        sessions: list[date], calibration: int, evaluation: int
    ) -> list[dict[str, date]]:
        output: list[dict[str, date]] = []
        cursor = calibration
        while cursor + evaluation <= len(sessions):
            end = cursor + evaluation - 1
            output.append(
                {
                    "training_start": sessions[cursor - calibration],
                    "training_end": sessions[cursor - 1],
                    "evaluation_start": sessions[cursor],
                    "evaluation_end": sessions[end],
                }
            )
            cursor += evaluation
        return output

    def _sessions(self, symbols: list[str], start: date, end: date) -> list[date]:
        return list(
            self.session.scalars(
                select(MarketHistoryModel.date)
                .where(
                    MarketHistoryModel.symbol.in_(symbols),
                    MarketHistoryModel.date >= start,
                    MarketHistoryModel.date <= end,
                )
                .distinct()
                .order_by(MarketHistoryModel.date)
            )
        )

    @staticmethod
    def _compound(values: list[float]) -> float:
        return math.prod(1 + item for item in values) - 1

    @classmethod
    def _curve(cls, values: list[tuple[date, float]]) -> list[dict[str, float | str]]:
        equity = 1.0
        curve: list[dict[str, float | str]] = []
        for current_date, value in values:
            equity *= 1 + value
            curve.append({"date": current_date.isoformat(), "equity": equity})
        return curve

    @staticmethod
    def _concatenate_curves(
        curves: list[list[dict[str, float | str]]],
    ) -> list[dict[str, float | str]]:
        scale = 1.0
        output: list[dict[str, float | str]] = []
        for curve in curves:
            for point in curve:
                adjusted = scale * float(point["equity"])
                output.append({"date": str(point["date"]), "equity": adjusted})
            if curve:
                scale *= float(curve[-1]["equity"])
        return output

    @staticmethod
    def _curve_drawdown(curve: list[dict[str, float | str]]) -> float:
        values = pd.Series([float(item["equity"]) for item in curve], dtype=float)
        if values.empty:
            return 0.0
        return float((values / values.cummax() - 1).min())

    @classmethod
    def _metrics(
        cls,
        returns: pd.Series,
        benchmark: pd.Series,
        trades: list[BacktestTrade],
        *,
        turnover: float,
    ) -> BacktestMetrics:
        cumulative = cls._compound(returns.tolist())
        periods = len(returns)
        annualized = (1 + cumulative) ** (252 / max(1, periods * 5)) - 1
        standard_deviation = float(returns.std(ddof=0))
        volatility = standard_deviation * math.sqrt(252 / 5) if periods else 0
        mean = float(returns.mean()) if periods else 0
        sharpe = (
            mean / standard_deviation * math.sqrt(252 / 5)
            if periods > 1 and standard_deviation > 0
            else None
        )
        downside = returns[returns < 0]
        downside_deviation = float(downside.std(ddof=0))
        sortino = (
            mean / downside_deviation * math.sqrt(252 / 5)
            if len(downside) > 1 and downside_deviation > 0
            else None
        )
        curve = (1 + returns).cumprod()
        drawdown = curve / curve.cummax() - 1
        benchmark_return = cls._compound(benchmark.tolist())
        aligned_length = min(len(returns), len(benchmark))
        active = (
            returns.iloc[:aligned_length].reset_index(drop=True)
            - benchmark.iloc[:aligned_length].reset_index(drop=True)
        )
        active_deviation = float(active.std(ddof=0))
        information_ratio = (
            float(active.mean() / active_deviation * math.sqrt(252 / 5))
            if len(active) > 1 and active_deviation > 0
            else None
        )
        positives = [
            trade.net_return * trade.weight
            for trade in trades
            if trade.net_return > 0
        ]
        negatives = [
            trade.net_return * trade.weight
            for trade in trades
            if trade.net_return < 0
        ]
        return BacktestMetrics(
            cumulative_return=cumulative,
            annualized_return=annualized,
            volatility=volatility,
            sharpe=sharpe,
            sortino=sortino,
            max_drawdown=float(drawdown.min()) if not drawdown.empty else 0,
            hit_rate=(
                sum(trade.net_return > 0 for trade in trades) / len(trades)
                if trades
                else 0
            ),
            average_trade=(
                sum(trade.net_return for trade in trades) / len(trades)
                if trades
                else 0
            ),
            profit_factor=(
                sum(positives) / abs(sum(negatives)) if negatives else None
            ),
            turnover=turnover,
            benchmark_return=benchmark_return,
            relative_return=cumulative - benchmark_return,
            information_ratio=information_ratio,
            benchmark_win_rate=(
                float((returns.iloc[:aligned_length].reset_index(drop=True)
                       > benchmark.iloc[:aligned_length].reset_index(drop=True)).mean())
                if aligned_length
                else None
            ),
        )
