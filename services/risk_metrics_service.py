"""Convenciones únicas para riesgo y costos de simulación."""

from typing import cast

import numpy as np


def value_at_risk(returns: np.ndarray, confidence: float) -> float:
    """VaR histórico como magnitud positiva de pérdida."""
    return max(0.0, -float(np.quantile(returns, 1 - confidence)))


def expected_shortfall(returns: np.ndarray, confidence: float) -> float:
    """Pérdida media condicional en la cola definida por VaR."""
    cutoff = -value_at_risk(returns, confidence)
    tail = returns[returns <= cutoff]
    return max(0.0, -float(tail.mean())) if len(tail) else 0.0


def path_drawdowns(daily_paths: np.ndarray) -> np.ndarray:
    """Máximo drawdown por trayectoria, con el capital inicial como primer pico."""
    cumulative = np.cumprod(1 + daily_paths, axis=1)
    peaks = np.maximum(1, np.maximum.accumulate(cumulative, axis=1))
    return cast(
        np.ndarray,
        np.maximum(0, -(cumulative / peaks - 1).min(axis=1)),
    )


def round_trip_cost_rate(
    transaction_cost_bps_per_side: float,
    slippage_bps_per_side: float,
) -> float:
    """Costo proporcional total de entrada y salida."""
    return 2 * (
        transaction_cost_bps_per_side + slippage_bps_per_side
    ) / 10_000
