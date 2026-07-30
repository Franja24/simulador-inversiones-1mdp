"""Asistente diario que compone snapshots existentes sin recalcularlos."""

import hashlib
import math
from datetime import UTC, date, datetime
from typing import Any, cast

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from config.competition import CompetitionConfig
from config.model_status import QUALITY_COVERAGE
from database.models import MarketHistoryModel
from domain.competition import (
    CompetitionCandidate,
    CompetitionDashboard,
    DailyBrief,
    LiquidityScore,
    RebalanceAdvice,
)
from repositories.competition_repository import CompetitionRepository
from repositories.price_repository import SqlPriceRepository
from services.portfolio_optimization_service import PortfolioOptimizationService
from services.portfolio_service import PortfolioService


class CompetitionIntelligenceService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = CompetitionRepository(session)
        self.portfolios = PortfolioService(session)

    @staticmethod
    def liquidity_score(
        symbol: str,
        estimated_spread: float,
        average_volume: float,
        trading_continuity: float,
        config: CompetitionConfig,
    ) -> LiquidityScore:
        spread_score = 100 * (1 - min(1.0, max(0.0, estimated_spread) / 0.05))
        volume_score = min(100.0, math.log10(1 + max(0.0, average_volume)) / 7 * 100)
        execution = min(
            100.0,
            max(0.0, 0.60 * volume_score + 0.40 * trading_continuity),
        )
        components = {
            "spread": spread_score,
            "volume": volume_score,
            "execution": execution,
        }
        total = sum(
            components[name] * config.liquidity_weights[name]
            for name in components
        )
        return LiquidityScore(
            symbol=symbol,
            score=round(total, 4),
            estimated_spread=estimated_spread,
            average_volume=average_volume,
            execution_ease=round(execution, 4),
            components={key: round(value, 4) for key, value in components.items()},
        )

    @staticmethod
    def competition_score(
        *,
        monte_carlo: float,
        aqs: float,
        momentum: float,
        beating_benchmark: float,
        liquidity: float,
        risk_penalty: float,
        config: CompetitionConfig,
    ) -> tuple[float, dict[str, float]]:
        components = {
            "monte_carlo": monte_carlo,
            "aqs": aqs,
            "momentum": momentum,
            "beating_benchmark": beating_benchmark * 100,
            "liquidity": liquidity,
            "risk": 100 - risk_penalty,
        }
        contributions = {
            key: max(0.0, min(100.0, value)) * config.weights[key]
            for key, value in components.items()
        }
        return round(sum(contributions.values()), 4), contributions

    def build_dashboard(
        self,
        portfolio_id: int,
        effective_date: date,
        config: CompetitionConfig | None = None,
        *,
        persist: bool = True,
    ) -> CompetitionDashboard:
        cfg = config or CompetitionConfig()
        portfolio = self.portfolios.get_required(portfolio_id)
        prices = SqlPriceRepository(self.session)
        valuation = self.portfolios.valuation(portfolio_id, prices)
        positions = self.portfolios.calculate_positions(portfolio_id, prices)
        current_weights = {
            item.symbol: float(item.portfolio_weight) / 100 for item in positions
        }
        aqs_rows = self.repository.latest_aqs(effective_date)
        simulations = self.repository.latest_asset_simulations(effective_date)
        optimization = self.repository.latest_optimization(effective_date)
        regime = self.repository.latest_regime(
            portfolio.benchmark_symbol, effective_date
        )
        warnings: list[str] = []
        if not aqs_rows:
            warnings.append("No existe snapshot AQS compatible con la fecha.")
        if not simulations:
            warnings.append("No existen simulaciones Monte Carlo por activo.")
        candidates = self._candidates(
            aqs_rows, simulations, effective_date, cfg
        )[: cfg.top_n]
        if not candidates:
            warnings.append("No hay candidatos con AQS y Monte Carlo disponibles.")
        optimal_weights, optimal_expected = self._optimal(optimization)
        current_expected = sum(
            current_weights.get(symbol, 0)
            * self._expected_return(payload)
            for symbol, payload in simulations.items()
        )
        rebalance = self.rebalance_advice(
            current_weights,
            optimal_weights,
            float(valuation["total"]),
            current_expected,
            optimal_expected,
            cfg,
        )
        benchmark_return = self._benchmark_return(
            portfolio.benchmark_symbol,
            portfolio.challenge_start_date,
            effective_date,
        )
        portfolio_return = float(valuation["return_percentage"]) / 100
        confidence_values = [item.confidence for item in candidates]
        confidence = (
            sum(confidence_values) / len(confidence_values)
            if confidence_values
            else float(regime["confidence"] if regime else 0)
        )
        risk_penalty = self._portfolio_risk_penalty(
            current_weights, simulations, candidates
        )
        dashboard = CompetitionDashboard(
            portfolio_id=portfolio_id,
            effective_date=effective_date,
            generated_at=datetime.combine(
                effective_date, datetime.min.time(), tzinfo=UTC
            ),
            capital_initial=float(portfolio.initial_capital),
            portfolio_value=float(valuation["total"]),
            buying_power=float(valuation["cash"]),
            benchmark_symbol=portfolio.benchmark_symbol,
            benchmark_return=benchmark_return,
            portfolio_return=portfolio_return,
            excess_return=portfolio_return - benchmark_return,
            market_regime=str(regime["regime"] if regime else "UNKNOWN"),
            confidence=max(0, min(100, confidence)),
            risk_level=self._risk_level(risk_penalty),
            model_status="VALIDATED" if QUALITY_COVERAGE >= 90 else "REVIEW",
            last_update=self.session.scalar(
                select(func.max(MarketHistoryModel.date)).where(
                    MarketHistoryModel.date <= effective_date
                )
            ),
            top_candidates=candidates,
            recommended_portfolio=optimal_weights,
            rebalance=rebalance,
            warnings=warnings,
        )
        if persist:
            signature = self._signature(aqs_rows, simulations, optimization)
            self.repository.save_snapshot(
                dashboard, cfg.model_version, signature
            )
        return dashboard

    def daily_brief(self, dashboard: CompetitionDashboard) -> DailyBrief:
        top = [
            f"{item.symbol} ({item.competition_score:.1f})"
            for item in dashboard.top_candidates[:5]
        ]
        markdown = "\n".join(
            [
                f"# Daily Brief - {dashboard.effective_date.isoformat()}",
                "",
                f"- Mercado: {dashboard.benchmark_symbol}",
                f"- Régimen: {dashboard.market_regime}",
                f"- Confianza: {dashboard.confidence:.1f}/100",
                f"- Riesgo: {dashboard.risk_level}",
                f"- Top candidatos: {', '.join(top) or 'Sin candidatos'}",
                (
                    "- Rebalanceo: "
                    f"{'Sí' if dashboard.rebalance.recommend else 'No'} - "
                    f"{dashboard.rebalance.recommendation}"
                ),
                "",
                "## Justificación",
                dashboard.rebalance.justification,
                "",
                "## Candidatos",
                *[
                    f"- **{item.symbol}**: {item.main_reason}. "
                    f"AQS {item.aqs:.1f}, MC {item.monte_carlo:.1f}, "
                    f"liquidez {item.liquidity.score:.1f}, "
                    f"riesgo {item.risk_penalty:.1f}."
                    for item in dashboard.top_candidates[:5]
                ],
                "",
                "> Documento informativo; no constituye asesoría financiera.",
            ]
        )
        return DailyBrief(
            effective_date=dashboard.effective_date,
            market=dashboard.benchmark_symbol,
            regime=dashboard.market_regime,
            confidence=dashboard.confidence,
            top_candidates=top,
            risk=dashboard.risk_level,
            rebalance_recommended=dashboard.rebalance.recommend,
            recommendation=dashboard.rebalance.recommendation,
            justification=dashboard.rebalance.justification,
            markdown=markdown,
        )

    @staticmethod
    def rebalance_advice(
        current_weights: dict[str, float],
        optimal_weights: dict[str, float],
        capital: float,
        current_expected_return: float,
        optimal_expected_return: float,
        config: CompetitionConfig,
    ) -> RebalanceAdvice:
        if not optimal_weights:
            return RebalanceAdvice(
                current_weights=current_weights,
                optimal_weights={},
                purchases={},
                sales={},
                expected_cost=0,
                expected_benefit=0,
                turnover=0,
                recommend=False,
                recommendation="MANTENER",
                justification="No existe un portafolio óptimo persistido compatible.",
            )
        raw = PortfolioOptimizationService.rebalance(
            current_weights,
            optimal_weights,
            capital,
            config.transaction_cost_bps_per_side,
        )
        cost = cast(float, raw["estimated_cost"])
        gross_benefit = (optimal_expected_return - current_expected_return) * capital
        net_benefit = gross_benefit - cost
        turnover = cast(float, raw["turnover"])
        recommend = (
            net_benefit >= config.minimum_rebalance_benefit_mxn
            and turnover <= config.maximum_recommended_turnover
        )
        reason = (
            f"Beneficio neto esperado ${net_benefit:,.2f}, costo "
            f"${cost:,.2f} y turnover {turnover:.1%}."
        )
        return RebalanceAdvice(
            current_weights=current_weights,
            optimal_weights=optimal_weights,
            purchases=cast(dict[str, float], raw["purchases"]),
            sales=cast(dict[str, float], raw["sales"]),
            expected_cost=cost,
            expected_benefit=net_benefit,
            turnover=turnover,
            recommend=recommend,
            recommendation="REBALANCEAR" if recommend else "MANTENER",
            justification=reason,
        )

    def _candidates(
        self,
        aqs_rows: list[dict[str, Any]],
        simulations: dict[str, dict[str, Any]],
        effective_date: date,
        config: CompetitionConfig,
    ) -> list[CompetitionCandidate]:
        output: list[CompetitionCandidate] = []
        for row in aqs_rows:
            symbol = str(row["symbol"])
            simulation = simulations.get(symbol)
            if simulation is None or not simulation.get("horizons"):
                continue
            horizon = simulation["horizons"][-1]
            expected = float(horizon["expected_return"])
            monte_carlo = max(0.0, min(100.0, 50 + expected * 500))
            momentum = max(0.0, min(100.0, 50 + float(row["momentum"]) * 500))
            es = float(horizon["expected_shortfall"])
            drawdown = float(horizon["expected_drawdown"])
            var = float(horizon["value_at_risk"])
            risk_penalty = min(100.0, (es + drawdown + var) / 3 * 500)
            liquidity = self._liquidity_from_history(
                symbol, effective_date, config
            )
            beating = float(horizon.get("probability_beating_benchmark") or 0)
            score, contributions = self.competition_score(
                monte_carlo=monte_carlo,
                aqs=float(row["aqs"]),
                momentum=momentum,
                beating_benchmark=beating,
                liquidity=liquidity.score,
                risk_penalty=risk_penalty,
                config=config,
            )
            main = max(contributions, key=lambda key: contributions[key])
            output.append(
                CompetitionCandidate(
                    symbol=symbol,
                    competition_score=score,
                    aqs=float(row["aqs"]),
                    monte_carlo=monte_carlo,
                    momentum=momentum,
                    probability_beating_benchmark=beating,
                    liquidity=liquidity,
                    risk_penalty=risk_penalty,
                    confidence=min(
                        float(row["confidence"]),
                        float(simulation.get("confidence", 0)),
                    ),
                    expected_return=expected,
                    expected_shortfall=es,
                    expected_drawdown=drawdown,
                    market_regime=str(row["regime"]),
                    main_reason=f"Mayor aporte: {main}",
                    explanation={
                        "AQS": f"Score persistido {float(row['aqs']):.1f}/100.",
                        "Monte Carlo": f"Retorno esperado {expected:.2%}.",
                        "Riesgo": (
                            f"ES {es:.2%}, VaR {var:.2%}, drawdown {drawdown:.2%}."
                        ),
                        "Régimen": str(row["regime"]),
                        "Liquidez": (
                            f"Score {liquidity.score:.1f}, spread "
                            f"{liquidity.estimated_spread:.2%}."
                        ),
                        "Score final": f"{score:.2f}/100.",
                    },
                )
            )
        output.sort(key=lambda item: (-item.competition_score, item.symbol))
        return [item.model_copy(update={"rank": rank}) for rank, item in enumerate(output, 1)]

    def _liquidity_from_history(
        self, symbol: str, effective_date: date, config: CompetitionConfig
    ) -> LiquidityScore:
        rows = list(
            self.session.scalars(
                select(MarketHistoryModel)
                .where(
                    MarketHistoryModel.symbol == symbol,
                    MarketHistoryModel.date <= effective_date,
                )
                .order_by(desc(MarketHistoryModel.date))
                .limit(config.lookback_sessions)
            )
        )
        valid = [item for item in rows if item.close > 0]
        spread = (
            sum((item.high - item.low) / item.close for item in valid) / len(valid)
            if valid
            else 0.05
        )
        average_volume = (
            sum(item.volume for item in valid) / len(valid) if valid else 0
        )
        continuity = (
            sum(item.volume > 0 for item in valid) / config.lookback_sessions * 100
        )
        return self.liquidity_score(
            symbol, spread, average_volume, continuity, config
        )

    def _benchmark_return(
        self, symbol: str, start: date | None, end: date
    ) -> float:
        rows = list(
            self.session.scalars(
                select(MarketHistoryModel)
                .where(
                    MarketHistoryModel.symbol == symbol.upper(),
                    MarketHistoryModel.date <= end,
                    *(
                        [MarketHistoryModel.date >= start]
                        if start is not None
                        else []
                    ),
                )
                .order_by(MarketHistoryModel.date)
            )
        )
        return (
            rows[-1].adj_close / rows[0].adj_close - 1
            if len(rows) >= 2 and rows[0].adj_close
            else 0
        )

    @staticmethod
    def _expected_return(payload: dict[str, Any]) -> float:
        horizons = payload.get("horizons", [])
        return float(horizons[-1]["expected_return"]) if horizons else 0

    @staticmethod
    def _optimal(payload: dict[str, Any] | None) -> tuple[dict[str, float], float]:
        if not payload or not payload.get("candidates"):
            return {}, 0
        candidate = payload["candidates"][0]
        return (
            {str(key): float(value) for key, value in candidate["weights"].items()},
            float(candidate["expected_return"]),
        )

    @staticmethod
    def _risk_level(penalty: float) -> str:
        if penalty >= 65:
            return "ALTO"
        if penalty >= 35:
            return "MEDIO"
        return "BAJO"

    @staticmethod
    def _portfolio_risk_penalty(
        current_weights: dict[str, float],
        simulations: dict[str, dict[str, Any]],
        candidates: list[CompetitionCandidate],
    ) -> float:
        weighted = 0.0
        invested = 0.0
        for symbol, weight in current_weights.items():
            payload = simulations.get(symbol)
            if payload is None or not payload.get("horizons"):
                continue
            horizon = payload["horizons"][-1]
            penalty = (
                float(horizon["expected_shortfall"])
                + float(horizon["expected_drawdown"])
                + float(horizon["value_at_risk"])
            ) / 3 * 500
            weighted += min(100.0, penalty) * weight
            invested += weight
        if invested > 0:
            return weighted / invested
        return (
            sum(item.risk_penalty for item in candidates) / len(candidates)
            if candidates
            else 100
        )

    @staticmethod
    def _signature(
        aqs: list[dict[str, Any]],
        simulations: dict[str, dict[str, Any]],
        optimization: dict[str, Any] | None,
    ) -> str:
        material = (
            f"{aqs}|"
            f"{sorted((key, value.get('data_signature')) for key, value in simulations.items())}|"
            f"{optimization.get('data_signature') if optimization else None}"
        )
        return hashlib.sha256(material.encode()).hexdigest()
