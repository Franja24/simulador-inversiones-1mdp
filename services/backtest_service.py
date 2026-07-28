"""Backtesting walk-forward de rankings AQS con ejecución mínima en D+1."""

import hashlib
import math
import random
from datetime import UTC, date, datetime
from typing import cast

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.quant_score import BacktestConfig, QuantScoreConfig
from database.models import MarketHistoryModel
from domain.quant import BacktestMetrics, BacktestResult, BacktestTrade
from repositories.quant_repository import QuantRepository
from services.quant_score_service import QuantScoreService


class BacktestService:
    """Evalúa señales históricas sin permitir precios posteriores al corte."""

    BIAS_WARNINGS = [
        "La señal del cierre D se ejecuta en la apertura de D+1.",
        "El universo histórico provisto puede contener sesgo de supervivencia.",
        "No se optimizan pesos usando el periodo evaluado.",
        "Benchmark y emisoras se comparan solo en fechas disponibles.",
        "Los costos configurados se descuentan de cada entrada y salida.",
    ]

    def __init__(self, session: Session) -> None:
        self.session = session
        self.scores = QuantScoreService(session)
        self.repository = QuantRepository(session)

    def run(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        benchmark_symbol: str,
        score_config: QuantScoreConfig | None = None,
        backtest_config: BacktestConfig | None = None,
    ) -> BacktestResult:
        score_cfg = score_config or QuantScoreConfig()
        test_cfg = backtest_config or BacktestConfig()
        universe = sorted({item.strip().upper() for item in symbols if item.strip()})
        sessions = self._sessions(universe, start_date, end_date)
        if len(sessions) <= test_cfg.holding_period + 1:
            raise ValueError("El rango no contiene sesiones suficientes.")
        rebalance_indices = range(
            0,
            len(sessions) - test_cfg.holding_period - 1,
            test_cfg.rebalance_frequency,
        )
        period_returns: list[tuple[date, float]] = []
        benchmark_returns: list[tuple[date, float]] = []
        trades: list[BacktestTrade] = []
        random_returns: list[float] = []
        momentum_returns: list[float] = []
        universe_returns: list[float] = []
        rng = random.Random(test_cfg.random_seed)
        for index in rebalance_indices:
            signal_date = sessions[index]
            execution_date = sessions[index + 1]
            exit_index = min(index + 1 + test_cfg.holding_period, len(sessions) - 1)
            exit_date = sessions[exit_index]
            results = self.scores.calculate_universe(
                universe,
                signal_date,
                benchmark_symbol,
                score_cfg,
                force=True,
            )
            ranking = self.scores.rank_universe(
                results, minimum_confidence=test_cfg.minimum_confidence
            )
            selected = [item.symbol for item in ranking[: test_cfg.top_n]]
            returns = self._period_returns(universe, execution_date, exit_date)
            weight = min(
                test_cfg.maximum_symbol_weight,
                1 / len(selected) if selected else 0,
            )
            net_period = 0.0
            for symbol in selected:
                prices = self._execution_prices(symbol, execution_date, exit_date)
                if prices is None:
                    continue
                entry, exit_price, actual_execution, actual_exit = prices
                gross = exit_price / entry - 1
                cost = test_cfg.transaction_cost_bps / 10_000 * 2
                net = gross - cost
                net_period += weight * net
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
            period_returns.append((exit_date, net_period))
            benchmark_returns.append(
                (exit_date, self._symbol_return(benchmark_symbol, execution_date, exit_date) or 0)
            )
            valid_returns = [
                cast(float, value) for value in returns.values() if value is not None
            ]
            universe_returns.append(
                sum(valid_returns) / len(valid_returns) if valid_returns else 0
            )
            random_symbols = rng.sample(
                universe, min(test_cfg.top_n, len(universe))
            )
            random_values = [
                cast(float, returns[item])
                for item in random_symbols
                if returns[item] is not None
            ]
            random_returns.append(
                sum(random_values) / len(random_values) if random_values else 0
            )
            momentum_top = sorted(
                results,
                key=lambda item: (
                    -next(
                        (
                            component.raw_value or float("-inf")
                            for component in item.components
                            if component.name == "momentum_20"
                        ),
                        float("-inf"),
                    ),
                    item.symbol,
                ),
            )[: test_cfg.top_n]
            momentum_values = [
                cast(float, returns[item.symbol])
                for item in momentum_top
                if returns[item.symbol] is not None
            ]
            momentum_returns.append(
                sum(momentum_values) / len(momentum_values) if momentum_values else 0
            )
        returns_series = pd.Series([item[1] for item in period_returns], dtype=float)
        benchmark_series = pd.Series([item[1] for item in benchmark_returns], dtype=float)
        equity_curve = self._curve(period_returns)
        benchmark_curve = self._curve(benchmark_returns)
        metrics = self._metrics(returns_series, benchmark_series, trades)
        run_material = (
            f"{universe}|{start_date}|{end_date}|{benchmark_symbol}|"
            f"{score_cfg.model_dump_json()}|{test_cfg.model_dump_json()}"
        )
        result = BacktestResult(
            run_id=hashlib.sha256(run_material.encode()).hexdigest()[:24],
            generated_at=datetime.now(UTC),
            model_version=score_cfg.model_version,
            start_date=start_date,
            end_date=end_date,
            benchmark_symbol=benchmark_symbol.upper(),
            equity_curve=equity_curve,
            benchmark_curve=benchmark_curve,
            trades=trades,
            metrics=metrics,
            comparison={
                "aqs": metrics.cumulative_return,
                "benchmark": metrics.benchmark_return or 0,
                "equal_weight_universe": self._compound(universe_returns),
                "random_selection": self._compound(random_returns),
                "momentum_20": self._compound(momentum_returns),
                "cash": 0.0,
            },
            walk_forward_periods=self.walk_forward_periods(
                sessions, test_cfg.calibration_sessions, test_cfg.evaluation_sessions
            ),
            warnings=self.BIAS_WARNINGS,
            configuration={
                "score": score_cfg.model_dump(),
                "backtest": test_cfg.model_dump(),
                "universe": universe,
            },
        )
        self.repository.save_backtest(result)
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
                            1, round(backtest_config.rebalance_frequency * 1.2)
                        )
                    }
                ),
            ),
            (
                "horizonte_+1",
                score_config,
                backtest_config.model_copy(
                    update={"holding_period": backtest_config.holding_period + 1}
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
        returns = [float(item["cumulative_return"]) for item in output]
        fragile = max(returns) - min(returns) > 0.20 if returns else False
        for item in output:
            item["fragile"] = fragile
        return output

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

    @staticmethod
    def walk_forward_periods(
        sessions: list[date], calibration: int, evaluation: int
    ) -> list[dict[str, str | float]]:
        periods: list[dict[str, str | float]] = []
        cursor = calibration
        while cursor < len(sessions):
            end = min(cursor + evaluation - 1, len(sessions) - 1)
            periods.append(
                {
                    "training_start": sessions[cursor - calibration].isoformat(),
                    "training_end": sessions[cursor - 1].isoformat(),
                    "evaluation_start": sessions[cursor].isoformat(),
                    "evaluation_end": sessions[end].isoformat(),
                    "weights_calibrated": 0.0,
                }
            )
            cursor += evaluation
        return periods

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

    def _execution_prices(
        self, symbol: str, execution: date, exit_date: date
    ) -> tuple[float, float, date, date] | None:
        entry = self.session.scalar(
            select(MarketHistoryModel)
            .where(
                MarketHistoryModel.symbol == symbol,
                MarketHistoryModel.date >= execution,
            )
            .order_by(MarketHistoryModel.date)
            .limit(1)
        )
        exit_bar = self.session.scalar(
            select(MarketHistoryModel)
            .where(
                MarketHistoryModel.symbol == symbol,
                MarketHistoryModel.date >= exit_date,
            )
            .order_by(MarketHistoryModel.date)
            .limit(1)
        )
        if entry is None or exit_bar is None or exit_bar.date <= entry.date:
            return None
        return entry.open, exit_bar.close, entry.date, exit_bar.date

    def _symbol_return(
        self, symbol: str, start: date, end: date
    ) -> float | None:
        prices = self._execution_prices(symbol.upper(), start, end)
        return prices[1] / prices[0] - 1 if prices else None

    def _period_returns(
        self, symbols: list[str], start: date, end: date
    ) -> dict[str, float | None]:
        return {symbol: self._symbol_return(symbol, start, end) for symbol in symbols}

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

    @classmethod
    def _metrics(
        cls,
        returns: pd.Series,
        benchmark: pd.Series,
        trades: list[BacktestTrade],
    ) -> BacktestMetrics:
        cumulative = cls._compound(returns.tolist())
        periods = len(returns)
        annualized = (1 + cumulative) ** (252 / max(1, periods * 5)) - 1
        volatility = float(returns.std(ddof=0) * math.sqrt(252 / 5)) if periods else 0
        mean = float(returns.mean()) if periods else 0
        return_std = float(returns.std(ddof=0))
        sharpe = (
            mean / return_std * math.sqrt(252 / 5)
            if periods > 1 and return_std > 0
            else None
        )
        downside = returns[returns < 0]
        downside_std = float(downside.std(ddof=0))
        sortino = (
            mean / downside_std * math.sqrt(252 / 5)
            if len(downside) > 1 and downside_std > 0
            else None
        )
        curve = (1 + returns).cumprod()
        drawdown = curve / curve.cummax() - 1
        benchmark_return = cls._compound(benchmark.tolist())
        active = returns.reset_index(drop=True) - benchmark.reset_index(drop=True)
        active_std = float(active.std(ddof=0))
        information_ratio = (
            float(active.mean() / active_std * math.sqrt(252 / 5))
            if len(active) > 1 and active_std > 0
            else None
        )
        positives = [trade.net_return for trade in trades if trade.net_return > 0]
        negatives = [trade.net_return for trade in trades if trade.net_return < 0]
        return BacktestMetrics(
            cumulative_return=cumulative,
            annualized_return=annualized,
            volatility=volatility,
            sharpe=sharpe,
            sortino=sortino,
            max_drawdown=float(drawdown.min()) if not drawdown.empty else 0,
            hit_rate=sum(trade.net_return > 0 for trade in trades) / len(trades) if trades else 0,
            average_trade=sum(trade.net_return for trade in trades) / len(trades) if trades else 0,
            profit_factor=sum(positives) / abs(sum(negatives)) if negatives else None,
            turnover=sum(trade.weight * 2 for trade in trades),
            benchmark_return=benchmark_return,
            relative_return=cumulative - benchmark_return,
            information_ratio=information_ratio,
            benchmark_win_rate=float((returns > benchmark).mean()) if periods else None,
        )
