"""Cálculo y cache persistente de indicadores técnicos informativos."""

from io import StringIO

import pandas as pd
from sqlalchemy.orm import Session

from repositories.market_history_repository import (
    IndicatorCacheRepository,
    MarketHistoryRepository,
)


class IndicatorService:
    """Calcula indicadores sin producir recomendaciones ni predicciones."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.history = MarketHistoryRepository(session)
        self.cache = IndicatorCacheRepository(session)

    def calculate(self, symbol: str, *, force: bool = False) -> pd.DataFrame:
        """Calcula o reutiliza cache cuando el histórico no cambió."""
        normalized = symbol.strip().upper()
        last_date = self.history.last_date(normalized)
        if last_date is None:
            return pd.DataFrame()
        cached = self.cache.get(normalized)
        if cached is not None and cached.last_history_date == last_date and not force:
            frame = pd.read_json(StringIO(cached.payload), orient="split")
            frame["date"] = pd.to_datetime(frame["date"]).dt.date
            return frame
        frame = self._history_frame(normalized)
        calculated = self._calculate_frame(frame)
        payload = calculated.to_json(orient="split", date_format="iso")
        self.cache.save(normalized, last_date, payload)
        self.session.commit()
        return calculated

    def _history_frame(self, symbol: str) -> pd.DataFrame:
        rows = self.history.list_history(symbol)
        return pd.DataFrame(
            [
                {
                    "date": row.date,
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "adj_close": row.adj_close,
                    "volume": row.volume,
                }
                for row in rows
            ]
        )

    @staticmethod
    def _calculate_frame(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.sort_values("date").drop_duplicates("date").reset_index(drop=True)
        close = result["adj_close"].astype(float)
        high = result["high"].astype(float)
        low = result["low"].astype(float)
        volume = result["volume"].astype(float)

        for window in (5, 10, 20, 50, 100, 200):
            result[f"sma_{window}"] = close.rolling(window).mean()
        for span in (5, 9, 20, 50):
            result[f"ema_{span}"] = close.ewm(span=span, adjust=False).mean()

        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
        relative_strength = gain / loss.replace(0, float("nan"))
        result["rsi_14"] = 100 - (100 / (1 + relative_strength))

        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        result["macd"] = ema_12 - ema_26
        result["macd_signal"] = result["macd"].ewm(span=9, adjust=False).mean()
        result["macd_histogram"] = result["macd"] - result["macd_signal"]

        previous_close = close.shift(1)
        true_range = pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        result["atr_14"] = true_range.ewm(alpha=1 / 14, adjust=False).mean()

        middle = close.rolling(20).mean()
        deviation = close.rolling(20).std()
        result["bollinger_middle"] = middle
        result["bollinger_upper"] = middle + 2 * deviation
        result["bollinger_lower"] = middle - 2 * deviation

        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
        atr = result["atr_14"].replace(0, float("nan"))
        plus_di = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr
        minus_di = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr
        result["adx_14"] = (
            100
            * (plus_di - minus_di).abs()
            / (plus_di + minus_di).replace(0, float("nan"))
        ).ewm(alpha=1 / 14, adjust=False).mean()

        result["roc_10"] = close.pct_change(10) * 100
        result["momentum_10"] = close - close.shift(10)
        result["daily_return"] = close.pct_change()
        result["weekly_return"] = close.pct_change(5)
        result["monthly_return"] = close.pct_change(21)
        result["rolling_volatility_20"] = (
            result["daily_return"].rolling(20).std() * (252**0.5)
        )
        result["average_volume_20"] = volume.rolling(20).mean()
        result["relative_volume"] = volume / result["average_volume_20"]
        result["high_52_week"] = high.rolling(252, min_periods=1).max()
        result["low_52_week"] = low.rolling(252, min_periods=1).min()
        result["distance_to_high"] = close / result["high_52_week"] - 1
        result["distance_to_low"] = close / result["low_52_week"] - 1
        return result
