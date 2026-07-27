"""Diagnóstico no bloqueante de calidad de históricos."""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DataQualityIssue:
    """Advertencia detectable sin detener la aplicación."""

    code: str
    message: str
    rows: int


class DataQualityService:
    """Detecta anomalías estructurales y financieras básicas."""

    def inspect(self, frame: pd.DataFrame) -> list[DataQualityIssue]:
        """Devuelve todas las advertencias encontradas."""
        if frame.empty:
            return [DataQualityIssue("EMPTY", "No existen datos históricos.", 0)]
        issues: list[DataQualityIssue] = []
        duplicates = int(frame.duplicated(subset=["date"]).sum())
        if duplicates:
            issues.append(
                DataQualityIssue("DUPLICATE_DATE", "Hay fechas duplicadas.", duplicates)
            )
        if not frame["date"].is_monotonic_increasing:
            issues.append(
                DataQualityIssue("OUT_OF_ORDER", "Las fechas están fuera de orden.", 1)
            )
        nan_rows = int(frame.isna().any(axis=1).sum())
        if nan_rows:
            issues.append(DataQualityIssue("NAN", "Existen valores vacíos.", nan_rows))
        negative_volume = int((frame["volume"] < 0).sum())
        if negative_volume:
            issues.append(
                DataQualityIssue(
                    "NEGATIVE_VOLUME", "Existe volumen negativo.", negative_volume
                )
            )
        invalid_close = int((frame["close"] <= 0).sum())
        if invalid_close:
            issues.append(
                DataQualityIssue(
                    "INVALID_CLOSE", "Existen cierres no positivos.", invalid_close
                )
            )
        returns = frame["close"].pct_change(fill_method=None)
        outliers = int((returns.abs() > 0.50).sum())
        if outliers:
            issues.append(
                DataQualityIssue(
                    "EXTREME_OUTLIER",
                    "Hay variaciones diarias superiores a 50%.",
                    outliers,
                )
            )
        return issues
