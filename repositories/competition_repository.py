"""Lectura de fuentes existentes y persistencia de Competition Intelligence."""

import json
from datetime import date
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from database.models import (
    CompetitionSnapshotModel,
    MarketRegimeSnapshotModel,
    QuantScoreComponentModel,
    QuantScoreResultModel,
    monte_carlo_runs,
    optimization_runs,
)
from domain.competition import CompetitionDashboard


class CompetitionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def latest_aqs(self, effective_date: date) -> list[dict[str, Any]]:
        latest = self.session.scalar(
            select(QuantScoreResultModel.effective_date)
            .where(QuantScoreResultModel.effective_date <= effective_date)
            .order_by(desc(QuantScoreResultModel.effective_date))
            .limit(1)
        )
        if latest is None:
            return []
        models = list(
            self.session.scalars(
                select(QuantScoreResultModel).where(
                    QuantScoreResultModel.effective_date == latest
                )
            )
        )
        output: list[dict[str, Any]] = []
        for model in models:
            momentum = self.session.scalar(
                select(QuantScoreComponentModel.raw_value).where(
                    QuantScoreComponentModel.result_id == model.id,
                    QuantScoreComponentModel.name == "momentum_20",
                )
            )
            output.append(
                {
                    "symbol": model.symbol,
                    "aqs": model.total_score,
                    "confidence": model.confidence,
                    "momentum": float(momentum or 0),
                    "regime": model.market_regime,
                    "benchmark": model.benchmark_symbol,
                }
            )
        return output

    def latest_asset_simulations(self, effective_date: date) -> dict[str, dict[str, Any]]:
        rows = self.session.execute(
            select(monte_carlo_runs.c.payload)
            .where(monte_carlo_runs.c.effective_date <= effective_date)
            .order_by(desc(monte_carlo_runs.c.created_at))
        ).scalars()
        output: dict[str, dict[str, Any]] = {}
        for raw in rows:
            payload = json.loads(raw)
            symbol = payload.get("symbol")
            if symbol and symbol not in output:
                output[str(symbol)] = payload
        return output

    def latest_optimization(self, effective_date: date) -> dict[str, Any] | None:
        raw = self.session.scalar(
            select(optimization_runs.c.payload)
            .where(optimization_runs.c.effective_date <= effective_date)
            .order_by(desc(optimization_runs.c.created_at))
            .limit(1)
        )
        return json.loads(raw) if raw else None

    def latest_regime(
        self, benchmark_symbol: str, effective_date: date
    ) -> dict[str, Any] | None:
        model = self.session.scalar(
            select(MarketRegimeSnapshotModel)
            .where(
                MarketRegimeSnapshotModel.benchmark_symbol
                == benchmark_symbol.upper(),
                MarketRegimeSnapshotModel.effective_date <= effective_date,
            )
            .order_by(desc(MarketRegimeSnapshotModel.effective_date))
            .limit(1)
        )
        if model is None:
            return None
        return {
            "regime": model.primary_regime,
            "confidence": model.confidence,
            "effective_date": model.effective_date,
        }

    def save_snapshot(
        self,
        dashboard: CompetitionDashboard,
        model_version: str,
        data_signature: str,
    ) -> CompetitionSnapshotModel:
        existing = self.session.scalar(
            select(CompetitionSnapshotModel).where(
                CompetitionSnapshotModel.portfolio_id == dashboard.portfolio_id,
                CompetitionSnapshotModel.effective_date == dashboard.effective_date,
                CompetitionSnapshotModel.model_version == model_version,
            )
        )
        payload = dashboard.model_dump(mode="json")
        values = {
            "benchmark_symbol": dashboard.benchmark_symbol,
            "competition_scores_json": json.dumps(
                {
                    item.symbol: item.competition_score
                    for item in dashboard.top_candidates
                }
            ),
            "top_candidates_json": json.dumps(
                [item.model_dump(mode="json") for item in dashboard.top_candidates]
            ),
            "recommended_portfolio_json": json.dumps(
                dashboard.recommended_portfolio
            ),
            "risk_json": json.dumps(
                {
                    "level": dashboard.risk_level,
                    "warnings": dashboard.warnings,
                }
            ),
            "rebalance_json": dashboard.rebalance.model_dump_json(),
            "dashboard_json": json.dumps(payload),
            "data_signature": data_signature,
        }
        if existing is None:
            existing = CompetitionSnapshotModel(
                portfolio_id=dashboard.portfolio_id,
                effective_date=dashboard.effective_date,
                model_version=model_version,
                **values,
            )
            self.session.add(existing)
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        self.session.commit()
        return existing

    def load_snapshot(
        self, portfolio_id: int, effective_date: date
    ) -> CompetitionDashboard | None:
        raw = self.session.scalar(
            select(CompetitionSnapshotModel.dashboard_json)
            .where(
                CompetitionSnapshotModel.portfolio_id == portfolio_id,
                CompetitionSnapshotModel.effective_date == effective_date,
            )
            .order_by(desc(CompetitionSnapshotModel.created_at))
            .limit(1)
        )
        return CompetitionDashboard.model_validate_json(raw) if raw else None
