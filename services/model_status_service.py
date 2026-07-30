"""Estado operativo y de calidad del modelo cuantitativo."""

import json
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from config.model_status import MODEL_VERSION, QUALITY_COVERAGE, QUALITY_TESTS
from database.models import MarketHistoryModel, monte_carlo_runs


class ModelStatusService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def snapshot(self, benchmark_symbol: str) -> dict[str, Any]:
        latest_payload = self.session.scalar(
            select(monte_carlo_runs.c.payload)
            .order_by(desc(monte_carlo_runs.c.created_at))
            .limit(1)
        )
        run = json.loads(latest_payload) if latest_payload else {}
        horizons = run.get("configuration", {}).get("horizons", [])
        return {
            "version": run.get("model_version", MODEL_VERSION),
            "coverage": QUALITY_COVERAGE,
            "tests": QUALITY_TESTS,
            "data_date": self.session.scalar(
                select(func.max(MarketHistoryModel.date))
            ),
            "benchmark": benchmark_symbol,
            "regime": run.get("regime", "Sin ejecución"),
            "monte_carlo_method": run.get("actual_method", "Sin ejecución"),
            "horizon": ", ".join(map(str, horizons)) if horizons else "Sin ejecución",
            "seed": run.get("seed", "Sin ejecución"),
            "data_signature": run.get("data_signature", "Sin ejecución"),
        }
