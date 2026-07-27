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

    INDICATOR_VERSION = "2.0-wilder"

    def __init__(
        self, session: Session, indicator_version: str | None = None
    ) -> None:
        self.session = session
        self.history = MarketHistoryRepository(session)
        self.cache = IndicatorCacheRepository(session)
        self.indicator_version = indicator_version or self.INDICATOR_VERSION

    def calculate(self, symbol: str, *, force: bool = False) -> pd.DataFrame:
        """Calcula o reutiliza cache cuando el histórico no cambió."""
        normalized = symbol.strip().upper()
        last_date, row_count, history_version = self.history.history_signature(
            normalized
        )
        if last_date is None:
            return pd.DataFrame()
        cached = self.cache.get(normalized)
        if (
            cached is not None
            and cached.last_history_date == last_date
            and cached.history_row_count == row_count
            and cached.history_version == history_version
            and cached.indicator_version == self.indicator_version
            and not force
        ):
            frame = pd.read_json(StringIO(cached.payload), orient="split")
            frame["date"] = pd.to_datetime(frame["date"]).dt.date
            return frame
        frame = self._history_frame(normalized)
        calculated = self._calculate_frame(frame)
        payload = calculated.to_json(orient="split", date_format="iso")
        self.cache.save(
            normalized,
            last_date,
            row_count,
            history_version,
            self.indicator_version,
            payload,
        )
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
        average_gain = IndicatorService._wilder_average(delta.clip(lower=0), 14)
        average_loss = IndicatorService._wilder_average(-delta.clip(upper=0), 14)
        rsi = pd.Series(float("nan"), index=result.index, dtype=float)
        gain_only = (average_gain > 0) & (average_loss == 0)
        loss_only = (average_gain == 0) & (average_loss > 0)
        unchanged = (average_gain == 0) & (average_loss == 0)
        regular = (average_gain > 0) & (average_loss > 0)
        rsi.loc[gain_only] = 100
        rsi.loc[loss_only] = 0
        rsi.loc[unchanged] = 50
        relative_strength = average_gain.loc[regular] / average_loss.loc[regular]
        rsi.loc[regular] = 100 - (100 / (1 + relative_strength))
        result["rsi_14"] = rsi

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
        result["atr_14"] = IndicatorService._wilder_average(true_range, 14)

        middle = close.rolling(20).mean()
        deviation = close.rolling(20).std()
        result["bollinger_middle"] = middle
        result["bollinger_upper"] = middle + 2 * deviation
        result["bollinger_lower"] = middle - 2 * deviation

        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
        atr = result["atr_14"]
        plus_smoothed = IndicatorService._wilder_average(plus_dm, 14)
        minus_smoothed = IndicatorService._wilder_average(minus_dm, 14)
        plus_di = 100 * plus_smoothed / atr.replace(0, float("nan"))
        minus_di = 100 * minus_smoothed / atr.replace(0, float("nan"))
        denominator = plus_di + minus_di
        dx = 100 * (plus_di - minus_di).abs() / denominator.replace(
            0, float("nan")
        )
        dx.loc[denominator == 0] = 0
        result["plus_di_14"] = plus_di.fillna(0)
        result["minus_di_14"] = minus_di.fillna(0)
        result["adx_14"] = IndicatorService._wilder_average(dx, 14)

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

    @staticmethod
    def _wilder_average(series: pd.Series, period: int) -> pd.Series:
        """Promedio de Wilder sin rellenar observaciones insuficientes."""
        values = series.astype(float)
        result = pd.Series(float("nan"), index=values.index, dtype=float)
        valid_positions = [position for position, value in enumerate(values) if pd.notna(value)]
        if len(valid_positions) < period:
            return result
        seed_positions = valid_positions[:period]
        seed_position = seed_positions[-1]
        previous = float(values.iloc[seed_positions].mean())
        result.iloc[seed_position] = previous
        for position in range(seed_position + 1, len(values)):
            current = values.iloc[position]
            if pd.isna(current):
                continue
            previous = ((previous * (period - 1)) + float(current)) / period
            result.iloc[position] = previous
        return result
