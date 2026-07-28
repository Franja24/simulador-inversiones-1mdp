"""Actinver Quant Score transparente, transversal y libre de red."""

from datetime import date

import pandas as pd
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.quant_score import QuantScoreConfig
from database.models import MarketHistoryModel
from domain.quant import QuantScoreResult as AQSResult
from domain.quant import RankingEntry, ScoreComponent
from repositories.quant_repository import QuantRepository, QuantUniverseRepository
from services.factor_normalization import normalize_factor
from services.indicator_service import IndicatorService
from services.market_regime_service import MarketRegimeService


class QuantScoreInput(BaseModel):
    """DTO legado conservado para compatibilidad con Fase 3."""

    symbol: str
    metrics: dict[str, float | None]


class QuantScoreResult(BaseModel):
    """DTO legado; los cálculos nuevos usan ``domain.quant.QuantScoreResult``."""

    symbol: str
    score: float = Field(ge=0, le=100)
    components: dict[str, float]
    methodology_version: str


class QuantScoreService:
    """Calcula AQS únicamente con históricos locales conocidos a la fecha efectiva."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = QuantRepository(session)
        self.regimes = MarketRegimeService(session)

    def calculate_symbol(
        self,
        symbol: str,
        effective_date: date,
        benchmark_symbol: str,
        config: QuantScoreConfig | None = None,
        *,
        universe: list[str] | None = None,
        force: bool = False,
    ) -> AQSResult:
        selected = universe
        if selected is None:
            selected = [
                item.symbol for item in QuantUniverseRepository(self.session).list_active()
            ]
        if not selected:
            raise ValueError(
                "calculate_symbol requiere un universo explícito o un universo "
                "cuantitativo activo persistente."
            )
        normalized = symbol.strip().upper()
        if normalized not in {item.strip().upper() for item in selected}:
            selected = [*selected, normalized]
        results = self.calculate_universe(
            selected,
            effective_date,
            benchmark_symbol,
            config or QuantScoreConfig(),
            force=force,
        )
        try:
            return next(item for item in results if item.symbol == normalized)
        except StopIteration as exc:
            raise ValueError(f"No hay datos calculables para {normalized}.") from exc

    def calculate_universe(
        self,
        symbols: list[str],
        effective_date: date,
        benchmark_symbol: str,
        config: QuantScoreConfig,
        *,
        force: bool = False,
    ) -> list[AQSResult]:
        universe = sorted(
            {
                item.strip().upper()
                for item in symbols
                if item.strip() and item.strip().upper() != benchmark_symbol.upper()
            }
        )
        if not universe:
            return []
        raw = {
            symbol: self._raw_factors(
                symbol, effective_date, benchmark_symbol, config
            )
            for symbol in universe
        }
        normalized: dict[str, dict[str, float | None]] = {}
        for factor in config.weights:
            values = {symbol: factors.get(factor) for symbol, factors in raw.items()}
            normalized[factor] = normalize_factor(
                values,
                method=config.normalization_method,
                inverse=factor == "volatility",
                lower=config.winsor_lower,
                upper=config.winsor_upper,
            )
        regime = self.regimes.calculate(benchmark_symbol, effective_date)
        results = [
            self._assemble(
                symbol, effective_date, benchmark_symbol, raw[symbol], normalized,
                regime.primary_regime, regime.high_volatility, len(universe), config
            )
            for symbol in universe
        ]
        self.repository.save_regime(regime, config.model_version, force=force)
        self.repository.save_results(results, config, force=force)
        self.session.commit()
        return results

    def rank_universe(
        self,
        results: list[AQSResult],
        *,
        minimum_score: float = 0,
        minimum_confidence: float = 0,
        classification: str | None = None,
    ) -> list[RankingEntry]:
        eligible = [
            item
            for item in results
            if item.total_score >= minimum_score
            and item.confidence >= minimum_confidence
            and (classification is None or item.classification == classification)
        ]
        ordered = sorted(
            eligible, key=lambda item: (-item.total_score, -item.confidence, item.symbol)
        )
        previous = self.repository.previous_results(
            results[0].effective_date, results[0].model_version
        ) if results else []
        prior_order = {
            item.symbol: index
            for index, item in enumerate(
                sorted(previous, key=lambda row: (-row.total_score, row.symbol)), 1
            )
        }
        prior = {item.symbol: item for item in previous}
        entries: list[RankingEntry] = []
        for rank, item in enumerate(ordered, 1):
            factors = {component.name: component.raw_value for component in item.components}
            old = prior.get(item.symbol)
            entries.append(
                RankingEntry(
                    rank=rank,
                    symbol=item.symbol,
                    score=item.total_score,
                    base_score=item.base_score,
                    regime_adjustment=item.regime_adjustment,
                    classification=item.classification,
                    confidence=item.confidence,
                    daily_return=factors.get("daily_return"),
                    weekly_return=factors.get("momentum_5"),
                    monthly_return=factors.get("momentum_20"),
                    relative_strength=factors.get("relative_strength"),
                    volatility=factors.get("volatility"),
                    relative_volume=factors.get("volume"),
                    warnings=item.warnings,
                    score_change=(
                        round(item.total_score - old.total_score, 4)
                        if old is not None else None
                    ),
                    rank_change=(
                        prior_order[item.symbol] - rank
                        if item.symbol in prior_order else None
                    ),
                    classification_change=(
                        f"{old.classification} → {item.classification}"
                        if old is not None and old.classification != item.classification
                        else None
                    ),
                )
            )
        return entries

    @staticmethod
    def explain_score(result: AQSResult) -> list[str]:
        return [item.explanation for item in result.components] + result.warnings

    def load_saved_result(
        self, symbol: str, effective_date: date, model_version: str
    ) -> AQSResult | None:
        return self.repository.load_result(symbol, effective_date, model_version)

    def compare_versions(
        self, symbol: str, effective_date: date, versions: list[str]
    ) -> dict[str, float | None]:
        return {
            version: (
                result.total_score
                if (result := self.load_saved_result(symbol, effective_date, version))
                else None
            )
            for version in versions
        }

    def _raw_factors(
        self,
        symbol: str,
        effective_date: date,
        benchmark_symbol: str,
        config: QuantScoreConfig,
    ) -> dict[str, float | None]:
        frame = self._frame(symbol, effective_date)
        benchmark = self._frame(benchmark_symbol, effective_date)
        result: dict[str, float | None] = {
            key: None
            for key in [
                "daily_return", "momentum_5", "momentum_10", "momentum_20",
                "relative_strength", "trend", "volume", "volatility",
                "distance_to_high", "atr_relative", "drawdown_20", "row_count",
                "missing_ratio", "last_age", "adx_14",
            ]
        }
        result["row_count"] = float(len(frame))
        if frame.empty:
            return result
        result["last_age"] = float((effective_date - frame.index[-1]).days)
        expected_span = max(1, (frame.index[-1] - frame.index[0]).days)
        result["missing_ratio"] = max(0.0, 1 - len(frame) / (expected_span * 5 / 7 + 1))
        close = frame["adj_close"].astype(float)
        horizons = [
            (1, "daily_return"),
            (5, "momentum_5"),
            (10, "momentum_10"),
            (20, "momentum_20"),
        ]
        for days, key in horizons:
            if len(close) > days:
                result[key] = float(close.iloc[-1] / close.iloc[-days - 1] - 1)
        common = frame[["adj_close"]].join(
            benchmark[["adj_close"]], how="inner", lsuffix="_asset", rsuffix="_benchmark"
        )
        if len(common) > 20:
            asset_return = (
                common["adj_close_asset"].iloc[-1]
                / common["adj_close_asset"].iloc[-21]
                - 1
            )
            benchmark_return = (
                common["adj_close_benchmark"].iloc[-1]
                / common["adj_close_benchmark"].iloc[-21]
                - 1
            )
            result["relative_strength"] = float(asset_return - benchmark_return)
        if len(close) >= 50:
            sma20 = close.rolling(20).mean()
            sma50 = close.rolling(50).mean()
            ema9 = close.ewm(span=9, adjust=False).mean()
            ema20 = close.ewm(span=20, adjust=False).mean()
            macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
            signal = macd.ewm(span=9, adjust=False).mean()
            checks = [
                close.iloc[-1] > sma20.iloc[-1],
                sma20.iloc[-1] > sma50.iloc[-1],
                sma20.iloc[-1] > sma20.iloc[-6],
                ema9.iloc[-1] > ema20.iloc[-1],
                macd.iloc[-1] > signal.iloc[-1],
            ]
            indicators = IndicatorService._calculate_frame(
                frame.reset_index()
            )
            adx = float(indicators["adx_14"].iloc[-1])
            result["adx_14"] = adx if pd.notna(adx) else None
            strength_multiplier = (
                0.75 + min(0.25, adx / 100)
                if pd.notna(adx)
                else 0.75
            )
            result["trend"] = sum(checks) / len(checks) * strength_multiplier
        if len(frame) >= 20:
            average_volume = frame["volume"].tail(20).mean()
            relative_volume = (
                float(frame["volume"].iloc[-1] / average_volume)
                if average_volume > 0 else None
            )
            price_direction = result["daily_return"]
            result["volume"] = (
                relative_volume
                if relative_volume is not None and price_direction is not None
                and price_direction >= 0 else (
                    -relative_volume if relative_volume is not None else None
                )
            )
            if (
                config.minimum_liquidity is not None
                and average_volume < config.minimum_liquidity
            ):
                result["volume"] = None
            returns = close.pct_change()
            result["volatility"] = float(returns.tail(20).std() * (252**0.5))
            previous = close.shift(1)
            tr = pd.concat(
                [
                    frame["high"] - frame["low"],
                    (frame["high"] - previous).abs(),
                    (frame["low"] - previous).abs(),
                ], axis=1
            ).max(axis=1)
            result["atr_relative"] = float(tr.tail(14).mean() / close.iloc[-1])
            rolling_peak = close.tail(20).cummax()
            result["drawdown_20"] = float((close.tail(20) / rolling_peak - 1).min())
            high52 = float(close.tail(252).max())
            distance = float(close.iloc[-1] / high52 - 1)
            # Máximo score cerca del máximo, pero no por encima de una extensión extrema.
            result["distance_to_high"] = -abs(
                distance + config.extreme_extension_threshold
            )
        return result

    def _assemble(
        self,
        symbol: str,
        effective_date: date,
        benchmark_symbol: str,
        raw: dict[str, float | None],
        normalized: dict[str, dict[str, float | None]],
        regime: str,
        high_volatility: bool,
        universe_size: int,
        config: QuantScoreConfig,
    ) -> AQSResult:
        warnings: list[str] = []
        components: list[ScoreComponent] = []
        available = 0
        for name, weight in config.weights.items():
            score = normalized[name][symbol]
            has_data = score is not None
            if has_data:
                available += 1
            else:
                warnings.append(f"Factor {name} sin datos; no aporta puntos.")
            normalized_score = float(score or 0)
            if name == "volatility" and score is not None:
                atr = float(raw.get("atr_relative") or 0)
                drawdown = abs(float(raw.get("drawdown_20") or 0))
                extra_risk = min(30.0, (atr + drawdown) * 100)
                normalized_score = max(
                    0,
                    normalized_score
                    - extra_risk * config.risk_penalty_intensity,
                )
            components.append(
                ScoreComponent(
                    name=name,
                    raw_value=raw.get(name),
                    normalized_score=normalized_score,
                    weight=weight,
                    weighted_score=normalized_score * weight,
                    explanation=(
                        f"{name}: valor {raw.get(name)!r}, percentil "
                        f"{normalized_score:.1f}, peso {weight:.0%}."
                        if has_data else f"{name}: datos insuficientes."
                    ),
                    data_available=has_data,
                )
            )
        base = sum(item.weighted_score for item in components)
        adjustment = self._regime_adjustment(raw, regime, high_volatility, config)
        total = max(0.0, min(100.0, base + adjustment))
        rows = int(raw.get("row_count") or 0)
        history_confidence = min(100, rows / config.minimum_history_rows * 100)
        factor_confidence = available / len(config.weights) * 100
        freshness = max(0, 100 - float(raw.get("last_age") or 0) * 15)
        gap_quality = max(0, 100 - float(raw.get("missing_ratio") or 0) * 100)
        universe_confidence = min(100, universe_size / 5 * 100)
        confidence = (
            history_confidence * 0.30
            + factor_confidence * 0.30
            + freshness * 0.15
            + gap_quality * 0.10
            + universe_confidence * 0.15
        )
        if high_volatility:
            confidence -= config.high_volatility_confidence_penalty
            warnings.append("Régimen de alta volatilidad: confianza reducida.")
        if rows < config.minimum_history_rows:
            warnings.append(
                f"Histórico insuficiente: {rows}/{config.minimum_history_rows} sesiones."
            )
        data_status = "OK"
        if universe_size < 3:
            confidence *= universe_size / 3
            data_status = "LIMITED_UNIVERSE"
            warnings.append(
                "LIMITED_UNIVERSE: se requieren al menos tres emisoras para una "
                "normalización transversal confiable."
            )
        return AQSResult(
            symbol=symbol,
            effective_date=effective_date,
            base_score=round(base, 4),
            regime_adjustment=round(adjustment, 4),
            total_score=round(total, 4),
            classification=self.classify(total),
            confidence=round(max(0, min(100, confidence)), 4),
            components=components,
            warnings=warnings,
            model_version=config.model_version,
            benchmark_symbol=benchmark_symbol.upper(),
            market_regime=regime,
            data_status=data_status,
        )

    @staticmethod
    def classify(score: float) -> str:
        if score >= 85:
            return "MUY_FUERTE"
        if score >= 70:
            return "FUERTE"
        if score >= 55:
            return "POSITIVA"
        if score >= 45:
            return "NEUTRAL"
        if score >= 30:
            return "DÉBIL"
        return "MUY_DÉBIL"

    @staticmethod
    def _regime_adjustment(
        raw: dict[str, float | None],
        regime: str,
        high_volatility: bool,
        config: QuantScoreConfig,
    ) -> float:
        if not config.regime_adjustment_enabled:
            return 0
        momentum = float(raw.get("momentum_20") or 0)
        volatility = float(raw.get("volatility") or 0)
        adjustment = 0.0
        if regime == "BULLISH":
            adjustment = min(5.0, max(-5.0, momentum * 50))
        elif regime == "SIDEWAYS":
            adjustment = -min(3.0, abs(momentum) * 20)
        elif regime == "BEARISH":
            adjustment = -min(7.0, volatility * config.risk_penalty_intensity * 10)
        if high_volatility:
            adjustment -= 2
        limit = config.maximum_regime_adjustment
        return max(-limit, min(limit, adjustment))

    def _frame(self, symbol: str, effective_date: date) -> pd.DataFrame:
        rows = list(
            self.session.scalars(
                select(MarketHistoryModel)
                .where(
                    MarketHistoryModel.symbol == symbol.strip().upper(),
                    MarketHistoryModel.date <= effective_date,
                )
                .order_by(MarketHistoryModel.date)
            )
        )
        return pd.DataFrame(
            [
                {
                    "date": row.date,
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "adj_close": row.adj_close,
                    "volume": row.volume,
                }
                for row in rows
            ]
        ).set_index("date") if rows else pd.DataFrame(
            columns=["open", "high", "low", "close", "adj_close", "volume"]
        )
