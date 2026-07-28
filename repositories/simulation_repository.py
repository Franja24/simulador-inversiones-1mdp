"""Persistencia compacta y reproducible de Fase 5."""

import json
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from database.models import (
    asset_simulation_results,
    candidate_weights,
    monte_carlo_runs,
    optimization_candidates,
    optimization_runs,
    portfolio_simulation_results,
    simulation_horizon_results,
    stress_test_results,
    stress_test_runs,
)


class SimulationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, run_id: str, payload: dict[str, Any], *, kind: str) -> None:
        table = {
            "simulation": monte_carlo_runs,
            "optimization": optimization_runs,
            "stress": stress_test_runs,
        }[kind]
        existing = self.session.execute(
            select(table.c.id).where(table.c.run_id == run_id)
        ).first()
        if existing is None:
            self.session.execute(
                insert(table).values(
                    run_id=run_id,
                    model_version=str(payload.get("model_version", "1")),
                    effective_date=payload.get("effective_date"),
                    data_signature=payload.get("data_signature"),
                    seed=payload.get("seed"),
                    status="OK",
                    payload=json.dumps(payload, default=str, ensure_ascii=False),
                )
            )

    def load(self, run_id: str, *, kind: str = "simulation") -> dict[str, Any] | None:
        table = {
            "simulation": monte_carlo_runs,
            "optimization": optimization_runs,
            "stress": stress_test_runs,
        }[kind]
        value = self.session.scalar(
            select(table.c.payload).where(table.c.run_id == run_id)
        )
        return json.loads(value) if value else None

    def save_simulation_details(
        self, run_id: str, payload: dict[str, Any], *, portfolio: bool
    ) -> None:
        table = portfolio_simulation_results if portfolio else asset_simulation_results
        self._detail(table, run_id, payload)
        for horizon in payload.get("horizons", []):
            self._detail(simulation_horizon_results, run_id, horizon)

    def save_optimization_details(
        self, run_id: str, payload: dict[str, Any]
    ) -> None:
        for candidate in payload.get("candidates", []):
            self._detail(optimization_candidates, run_id, candidate)
            self._detail(
                candidate_weights,
                run_id,
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "weights": candidate.get("weights", {}),
                },
            )

    def save_stress_details(self, run_id: str, payload: dict[str, Any]) -> None:
        self._detail(stress_test_results, run_id, payload)

    def _detail(self, table: Any, run_id: str, payload: dict[str, Any]) -> None:
        self.session.execute(
            insert(table).values(
                run_id=run_id,
                model_version=str(payload.get("model_version", "1")),
                effective_date=payload.get("effective_date"),
                data_signature=payload.get("data_signature"),
                seed=payload.get("seed"),
                status="OK",
                payload=json.dumps(payload, default=str, ensure_ascii=False),
            )
        )
