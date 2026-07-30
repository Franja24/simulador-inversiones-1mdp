"""Reporte Excel y exportaciones reproducibles de Fase 5."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pandas as pd
from openpyxl import Workbook

from domain.simulation import (
    OptimizationResult,
    PortfolioSimulationResult,
    StressScenarioResult,
)


class SimulationReportService:
    SHEETS = [
        "Resumen de simulación",
        "Configuración",
        "Datos utilizados",
        "Percentiles",
        "Probabilidades",
        "VaR y Expected Shortfall",
        "Drawdown",
        "Benchmark",
        "Trayectorias de muestra",
        "Portafolio actual",
        "Candidatos",
        "Pesos",
        "Optimización",
        "Robustez",
        "Stress testing",
        "Rebalanceo hipotético",
        "Advertencias",
    ]

    def generate(
        self,
        simulation: PortfolioSimulationResult,
        optimization: OptimizationResult | None = None,
        stress: list[StressScenarioResult] | None = None,
        output_dir: Path | None = None,
    ) -> Path:
        workbook = Workbook()
        workbook.remove(workbook.active)
        self._sheet(
            workbook,
            "Resumen de simulación",
            ["Concepto", "Valor"],
            [
                ["Fecha", datetime.now(UTC).replace(tzinfo=None)],
                ["Método", simulation.actual_method],
                ["Versión", simulation.model_version],
                ["Confianza", simulation.confidence],
                ["Universo", ", ".join(simulation.universe)],
                [
                    "Horizontes",
                    ", ".join(
                        map(
                            str,
                            cast(
                                list[object],
                                simulation.configuration.get("horizons", []),
                            ),
                        )
                    ),
                ],
                ["Semilla", simulation.seed],
                ["Firma de datos", simulation.data_signature],
                [
                    "Resumen ejecutivo",
                    (
                        "Escenarios reproducibles bajo supuestos históricos; "
                        "validar riesgos, restricciones y advertencias."
                    ),
                ],
            ],
        )
        self._sheet(
            workbook,
            "Configuración",
            ["Concepto", "JSON"],
            [
                ["Simulación", json.dumps(simulation.configuration)],
                ["Restricciones", json.dumps(simulation.restrictions)],
                ["Pesos", json.dumps(simulation.weights)],
            ],
        )
        self._sheet(workbook, "Datos utilizados", ["Firma"], [[simulation.data_signature]])
        self._sheet(
            workbook,
            "Percentiles",
            ["Horizonte", "Percentiles"],
            [
                [item.horizon_sessions, item.percentiles.model_dump_json()]
                for item in simulation.horizons
            ],
        )
        self._sheet(
            workbook,
            "Probabilidades",
            ["Horizonte", "Positiva", "Benchmark"],
            [
                [
                    item.horizon_sessions,
                    item.probability_positive,
                    item.probability_beating_benchmark,
                ]
                for item in simulation.horizons
            ],
        )
        self._sheet(
            workbook,
            "VaR y Expected Shortfall",
            ["Horizonte", "VaR", "ES"],
            [
                [item.horizon_sessions, item.value_at_risk, item.expected_shortfall]
                for item in simulation.horizons
            ],
        )
        self._sheet(
            workbook,
            "Drawdown",
            ["Horizonte", "Esperado", "P95"],
            [
                [item.horizon_sessions, item.expected_drawdown, item.drawdown_p95]
                for item in simulation.horizons
            ],
        )
        self._sheet(
            workbook,
            "Benchmark",
            ["Horizonte", "Probabilidad superar"],
            [
                [item.horizon_sessions, item.probability_beating_benchmark]
                for item in simulation.horizons
            ],
        )
        self._sheet(
            workbook,
            "Trayectorias de muestra",
            ["Horizonte", "JSON"],
            [[key, json.dumps(value)] for key, value in simulation.sample_paths.items()],
        )
        self._sheet(
            workbook,
            "Portafolio actual",
            ["Emisora", "Peso"],
            [[key, value] for key, value in simulation.weights.items()],
        )
        candidates = optimization.candidates if optimization else []
        rejected = optimization.rejected_candidates if optimization else []
        self._sheet(
            workbook,
            "Candidatos",
            ["ID", "Estado", "Score", "Retorno", "VaR", "ES", "Drawdown", "DD P95", "Motivos"],
            [
                [
                    item.candidate_id,
                    "ACEPTADO",
                    item.objective_score,
                    item.expected_return,
                    item.value_at_risk,
                    item.expected_shortfall,
                    item.expected_drawdown,
                    item.drawdown_p95,
                    "",
                ]
                for item in candidates
            ]
            + [
                [
                    item.candidate_id,
                    "RECHAZADO",
                    "",
                    "",
                    item.metrics.get("var"),
                    item.metrics.get("expected_shortfall"),
                    "",
                    "",
                    "; ".join(item.reasons),
                ]
                for item in rejected
            ],
        )
        self._sheet(
            workbook,
            "Pesos",
            ["ID", "Pesos JSON"],
            [[item.candidate_id, json.dumps(item.weights)] for item in candidates],
        )
        self._sheet(
            workbook,
            "Optimización",
            ["Concepto", "Valor"],
            (
                [
                    ["Objetivo solicitado", optimization.requested_objective],
                    ["Objetivo utilizado", optimization.used_objective],
                    ["Aceptados", len(optimization.candidates)],
                    ["Rechazados", len(optimization.rejected_candidates)],
                    ["Configuración", json.dumps(optimization.configuration)],
                    [
                        "Criterios",
                        json.dumps(
                            optimization.configuration.get(
                                "acceptance_criteria", {}
                            )
                        ),
                    ],
                ]
                if optimization
                else [["Estado", "No incluida"]]
            ),
        )
        self._sheet(workbook, "Robustez", ["Nota"], [["Evaluación disponible por candidato"]])
        self._sheet(
            workbook,
            "Stress testing",
            ["Escenario", "Impacto"],
            [[item.name, item.portfolio_impact] for item in (stress or [])],
        )
        self._sheet(
            workbook, "Rebalanceo hipotético", ["Nota"], [["No ejecuta operaciones reales"]]
        )
        self._sheet(
            workbook,
            "Advertencias",
            ["Advertencia"],
            [[item] for item in simulation.warnings] or [["Ninguna"]],
        )
        destination = output_dir or Path("data/exports")
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / f"reporte_fase5_{datetime.now():%Y-%m-%d_%H-%M-%S}.xlsx"
        workbook.save(path)
        return path

    @staticmethod
    def candidates_csv(result: OptimizationResult) -> bytes:
        accepted = [
            {
                **item.model_dump(),
                "status": "ACCEPTED",
                "rejection_reasons": "",
                "requested_objective": result.requested_objective,
                "used_objective": result.used_objective,
            }
            for item in result.candidates
        ]
        rejected = [
            {
                "candidate_id": item.candidate_id,
                "weights": item.weights,
                "status": "REJECTED",
                "rejection_reasons": "; ".join(item.reasons),
                **item.metrics,
                "requested_objective": result.requested_objective,
                "used_objective": result.used_objective,
            }
            for item in result.rejected_candidates
        ]
        return str(pd.DataFrame([*accepted, *rejected]).to_csv(index=False)).encode()

    @staticmethod
    def weights_csv(result: OptimizationResult) -> bytes:
        rows = [{"candidate_id": item.candidate_id, **item.weights} for item in result.candidates]
        return str(pd.DataFrame(rows).to_csv(index=False)).encode()

    @staticmethod
    def reproducible_json(result: PortfolioSimulationResult) -> bytes:
        return result.model_dump_json(indent=2).encode()

    @staticmethod
    def _sheet(workbook: Workbook, name: str, headers: list[str], rows: list[list[object]]) -> None:
        sheet = workbook.create_sheet(name)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
