"""Preparación auditable de retornos locales sin forward fill ni lookahead."""

import hashlib
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import MarketHistoryModel


class ReturnMatrixService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def build_asset_returns(
        self,
        symbol: str,
        effective_date: date,
        *,
        lookback_sessions: int,
        return_type: str = "simple",
        winsor_lower: float = 0.01,
        winsor_upper: float = 0.99,
    ) -> pd.Series:
        rows = self._rows(symbol, effective_date, lookback_sessions + 1)
        if len(rows) < 2:
            return pd.Series(dtype=float, name=symbol.upper())
        prices = pd.Series(
            [row.adj_close for row in rows],
            index=pd.Index([row.date for row in rows], name="date"),
            dtype=float,
            name=symbol.upper(),
        )
        if (prices <= 0).any():
            raise ValueError("Los precios deben ser positivos.")
        returns = np.log(prices / prices.shift(1)) if return_type == "log" else prices.pct_change()
        returns = returns.dropna()
        if not returns.empty:
            returns = returns.clip(
                returns.quantile(winsor_lower), returns.quantile(winsor_upper)
            )
        return returns

    def build_aligned_return_matrix(
        self,
        symbols: list[str],
        effective_date: date,
        *,
        lookback_sessions: int,
        return_type: str = "simple",
        winsor_lower: float = 0.01,
        winsor_upper: float = 0.99,
    ) -> pd.DataFrame:
        unique = list(dict.fromkeys(item.strip().upper() for item in symbols))
        series = [
            self.build_asset_returns(
                symbol,
                effective_date,
                lookback_sessions=lookback_sessions,
                return_type=return_type,
                winsor_lower=winsor_lower,
                winsor_upper=winsor_upper,
            )
            for symbol in unique
        ]
        if not series:
            return pd.DataFrame()
        return pd.concat(series, axis=1, join="inner").dropna().sort_index()

    @staticmethod
    def validate_history(
        matrix: pd.DataFrame,
        *,
        minimum_rows: int,
        maximum_missing_ratio: float,
    ) -> list[str]:
        warnings: list[str] = []
        if len(matrix) < minimum_rows:
            raise ValueError(
                f"Histórico insuficiente: {len(matrix)}/{minimum_rows} retornos."
            )
        missing_ratio = float(matrix.isna().mean().max()) if not matrix.empty else 1
        if missing_ratio > maximum_missing_ratio:
            raise ValueError("La proporción de datos faltantes excede el máximo.")
        if matrix.nunique().min() <= 1:
            warnings.append("Una o más series tienen volatilidad cero.")
        return warnings

    @staticmethod
    def data_signature(matrix: pd.DataFrame) -> str:
        digest = hashlib.sha256()
        digest.update("|".join(map(str, matrix.columns)).encode())
        for index, row in matrix.iterrows():
            digest.update(f"{index}|".encode())
            digest.update(np.asarray(row, dtype=np.float64).tobytes())
        return digest.hexdigest()

    @staticmethod
    def diagnostics(matrix: pd.DataFrame) -> dict[str, object]:
        return {
            "rows": len(matrix),
            "mean": matrix.mean().to_dict(),
            "median": matrix.median().to_dict(),
            "volatility": matrix.std(ddof=0).to_dict(),
            "skewness": matrix.skew().to_dict(),
            "kurtosis": matrix.kurt().to_dict(),
            "correlation": matrix.corr().to_dict(),
            "covariance": matrix.cov().to_dict(),
            "missing": matrix.isna().sum().to_dict(),
        }

    def _rows(
        self, symbol: str, effective_date: date, limit: int
    ) -> list[MarketHistoryModel]:
        rows = list(
            self.session.scalars(
                select(MarketHistoryModel)
                .where(
                    MarketHistoryModel.symbol == symbol.strip().upper(),
                    MarketHistoryModel.date <= effective_date,
                )
                .order_by(MarketHistoryModel.date.desc())
                .limit(limit)
            )
        )
        return list(reversed(rows))
