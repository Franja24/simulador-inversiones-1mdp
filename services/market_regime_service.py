"""Clasificación histórica del régimen usando solo datos disponibles."""

from datetime import date
from typing import Literal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import MarketHistoryModel
from domain.quant import MarketRegimeResult


class MarketRegimeService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def calculate(
        self, benchmark_symbol: str, effective_date: date
    ) -> MarketRegimeResult:
        symbol = benchmark_symbol.strip().upper()
        rows = list(
            self.session.scalars(
                select(MarketHistoryModel)
                .where(
                    MarketHistoryModel.symbol == symbol,
                    MarketHistoryModel.date <= effective_date,
                )
                .order_by(MarketHistoryModel.date)
            )
        )
        if len(rows) < 50:
            return MarketRegimeResult(
                effective_date=effective_date,
                benchmark_symbol=symbol,
                primary_regime="INSUFFICIENT_DATA",
                high_volatility=False,
                confidence=min(100, len(rows) / 50 * 100),
                metrics={},
                warnings=["Se requieren al menos 50 sesiones del benchmark."],
            )
        close = pd.Series([row.adj_close for row in rows], dtype=float)
        returns = close.pct_change()
        sma_20 = close.rolling(20).mean()
        sma_50 = close.rolling(50).mean()
        slope_20 = float(sma_20.iloc[-1] / sma_20.iloc[-6] - 1)
        volatility = returns.rolling(20).std() * (252**0.5)
        current_volatility = float(volatility.iloc[-1])
        historical = volatility.dropna()
        volatility_threshold = float(historical.quantile(0.80))
        high_volatility = (
            current_volatility > volatility_threshold or current_volatility > 0.60
        )
        peak = close.cummax()
        drawdown = close / peak - 1
        current = float(close.iloc[-1])
        above_20 = current > float(sma_20.iloc[-1])
        aligned_up = float(sma_20.iloc[-1]) > float(sma_50.iloc[-1])
        if above_20 and aligned_up and slope_20 > 0:
            regime: Literal["BULLISH", "BEARISH", "SIDEWAYS"] = "BULLISH"
        elif not above_20 and not aligned_up and slope_20 < 0:
            regime = "BEARISH"
        else:
            regime = "SIDEWAYS"
        return MarketRegimeResult(
            effective_date=effective_date,
            benchmark_symbol=symbol,
            primary_regime=regime,
            high_volatility=high_volatility,
            confidence=min(100, len(rows) / 100 * 100),
            metrics={
                "price": current,
                "sma_20": float(sma_20.iloc[-1]),
                "sma_50": float(sma_50.iloc[-1]),
                "sma_20_slope": slope_20,
                "volatility_20": current_volatility,
                "volatility_p80": volatility_threshold,
                "drawdown": float(drawdown.iloc[-1]),
            },
        )
