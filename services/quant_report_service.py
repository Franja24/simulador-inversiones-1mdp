"""Exportaciones reproducibles de AQS y backtesting."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from openpyxl import Workbook

from domain.quant import BacktestResult, QuantScoreResult, RankingEntry


class QuantReportService:
    DISCLAIMER = (
        "El AQS es una herramienta cuantitativa informativa. No garantiza "
        "rendimientos y no constituye asesoría financiera."
    )

    def generate(
        self,
        ranking: list[RankingEntry],
        results: list[QuantScoreResult],
        backtest: BacktestResult | None = None,
        output_dir: Path | None = None,
    ) -> Path:
        workbook = Workbook()
        workbook.remove(workbook.active)
        self._sheet(
            workbook,
            "Resumen",
            ["Concepto", "Valor"],
            [
                ["Fecha de generación", datetime.now(UTC).replace(tzinfo=None)],
                ["Versión", results[0].model_version if results else "N/D"],
                ["Fecha de datos", results[0].effective_date if results else "N/D"],
                ["Disclaimer", self.DISCLAIMER],
            ],
        )
        self._sheet(
            workbook,
            "Ranking actual",
            [
                "Rango", "Emisora", "AQS", "Base", "Ajuste", "Clasificación",
                "Confianza", "Cambio score", "Cambio ranking",
            ],
            [
                [
                    item.rank, item.symbol, item.score, item.base_score,
                    item.regime_adjustment, item.classification, item.confidence,
                    item.score_change, item.rank_change,
                ]
                for item in ranking
            ],
        )
        self._sheet(
            workbook,
            "Componentes",
            [
                "Emisora", "Factor", "Valor", "Score", "Peso", "Ponderado",
                "Explicación",
            ],
            [
                [
                    result.symbol, component.name, component.raw_value,
                    component.normalized_score, component.weight,
                    component.weighted_score, component.explanation,
                ]
                for result in results
                for component in result.components
            ],
        )
        self._sheet(
            workbook,
            "Régimen",
            ["Emisora", "Régimen", "Ajuste"],
            [
                [item.symbol, item.market_regime, item.regime_adjustment]
                for item in results
            ],
        )
        self._sheet(
            workbook, "Histórico de scores", ["Nota"], [["Persistido en SQLite"]]
        )
        if backtest is not None:
            self._sheet(
                workbook, "Backtest", ["Métrica", "Valor"],
                [[key, value] for key, value in backtest.metrics.model_dump().items()],
            )
            self._sheet(
                workbook, "Comparación", ["Estrategia", "Rendimiento"],
                [[key, value] for key, value in backtest.comparison.items()],
            )
            self._sheet(
                workbook, "Drawdown", ["Fecha", "Capital"],
                [[item["date"], item["equity"]] for item in backtest.equity_curve],
            )
            trade_headers = (
                list(backtest.trades[0].model_dump()) if backtest.trades else ["Nota"]
            )
            trade_rows = (
                [list(item.model_dump().values()) for item in backtest.trades]
                or [["Sin operaciones"]]
            )
            self._sheet(
                workbook, "Operaciones simuladas", trade_headers, trade_rows
            )
            configuration = backtest.configuration
            warnings = backtest.warnings
        else:
            for name in [
                "Backtest", "Comparación", "Drawdown", "Operaciones simuladas"
            ]:
                self._sheet(workbook, name, ["Nota"], [["No incluido"]])
            configuration = {}
            warnings = [warning for item in results for warning in item.warnings]
        self._sheet(
            workbook,
            "Configuración",
            ["JSON"],
            [[json.dumps(configuration, ensure_ascii=False, default=str)]],
        )
        self._sheet(
            workbook, "Advertencias", ["Advertencia"],
            [[item] for item in warnings] or [["Ninguna"]],
        )
        destination = output_dir or Path("data/exports")
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / f"reporte_aqs_{datetime.now():%Y-%m-%d_%H-%M-%S}.xlsx"
        workbook.save(path)
        return path

    @staticmethod
    def ranking_csv(ranking: list[RankingEntry]) -> bytes:
        content = pd.DataFrame([item.model_dump() for item in ranking]).to_csv(
            index=False
        )
        return str(content).encode("utf-8")

    @staticmethod
    def backtest_csv(backtest: BacktestResult) -> bytes:
        content = pd.DataFrame(
            [item.model_dump() for item in backtest.trades]
        ).to_csv(index=False)
        return str(content).encode("utf-8")

    @staticmethod
    def configuration_json(backtest: BacktestResult) -> bytes:
        return json.dumps(
            backtest.configuration, ensure_ascii=False, indent=2, default=str
        ).encode("utf-8")

    @staticmethod
    def _sheet(
        workbook: Workbook, name: str, headers: list[str], rows: list[list[object]]
    ) -> None:
        sheet = workbook.create_sheet(name)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
