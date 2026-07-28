"""Normalización transversal robusta y reproducible de factores."""

import math

import pandas as pd


def winsorize(values: pd.Series, lower: float = 0.05, upper: float = 0.95) -> pd.Series:
    """Recorta extremos sin utilizar observaciones de otras fechas."""
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.dropna()
    if valid.empty:
        return numeric.astype(float)
    return numeric.clip(valid.quantile(lower), valid.quantile(upper))


def normalize_factor(
    values: dict[str, float | None],
    *,
    method: str = "percentile_rank",
    inverse: bool = False,
    lower: float = 0.05,
    upper: float = 0.95,
) -> dict[str, float | None]:
    """Convierte un corte transversal a 0–100 conservando ausencias."""
    series = pd.Series(values, dtype=float)
    valid = winsorize(series.dropna(), lower, upper)
    if valid.empty:
        return dict.fromkeys(values)
    if method == "percentile_rank":
        if len(valid) == 1:
            normalized = pd.Series(50.0, index=valid.index)
        else:
            normalized = (valid.rank(method="average") - 1) / (len(valid) - 1) * 100
    elif method == "robust_zscore":
        median = float(valid.median())
        mad = float((valid - median).abs().median())
        if mad == 0:
            normalized = pd.Series(50.0, index=valid.index)
        else:
            robust_z = (valid - median) / (1.4826 * mad)
            normalized = robust_z.map(lambda item: 100 / (1 + math.exp(-item)))
    else:
        raise ValueError(f"Método no soportado: {method}")
    if inverse:
        normalized = 100 - normalized
    return {
        symbol: (
            round(float(normalized[symbol]), 8)
            if symbol in normalized.index
            else None
        )
        for symbol in values
    }

