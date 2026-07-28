"""Adaptador de Yahoo Finance mediante yfinance."""

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from domain.market import MarketBar, MarketBatchResult, MarketQuote
from providers.market_provider import MarketProvider, MarketProviderError


def normalize_yahoo_symbol(symbol: str) -> str:
    """Normaliza emisoras mexicanas sin alterar índices o símbolos calificados."""
    normalized = symbol.strip().upper()
    if not normalized:
        raise ValueError("La emisora es obligatoria.")
    if normalized.startswith("^") or "." in normalized or "=" in normalized:
        return normalized
    return f"{normalized}.MX"


class YahooProvider(MarketProvider):
    """Proveedor externo aislado del resto de la aplicación."""

    def __init__(self, client: Any | None = None, max_workers: int = 8) -> None:
        if max_workers < 1:
            raise ValueError("La concurrencia debe ser al menos uno.")
        self.max_workers = max_workers
        if client is None:
            try:
                import yfinance as yahoo_client
            except ImportError as exc:
                raise MarketProviderError(
                    "yfinance no está instalado; instala requirements.txt."
                ) from exc
            self.client: Any = yahoo_client
        else:
            self.client = client

    @property
    def provider_name(self) -> str:
        return "yahoo"

    @property
    def provider_version(self) -> str:
        return str(getattr(self.client, "__version__", "unknown"))

    @property
    def supported_markets(self) -> tuple[str, ...]:
        return ("BMV", "NASDAQ", "NYSE", "INDEX")

    def get_quote(self, symbol: str) -> MarketQuote:
        normalized = normalize_yahoo_symbol(symbol)
        try:
            ticker = self.client.Ticker(normalized)
            info = ticker.fast_info
            price = float(info["last_price"])
            previous = info.get("previous_close")
            volume = info.get("last_volume")
            timezone = info.get("timezone") or "America/Mexico_City"
        except Exception as exc:
            raise MarketProviderError(
                f"No fue posible obtener la cotización de {normalized}."
            ) from exc
        if not math.isfinite(price) or price <= 0:
            raise MarketProviderError(f"Yahoo devolvió un precio inválido para {normalized}.")
        return MarketQuote(
            symbol=normalized,
            price=price,
            previous_close=float(previous) if previous else None,
            volume=int(volume) if volume is not None else None,
            timestamp=datetime.now(UTC),
            timezone=str(timezone),
            provider=self.provider_name,
        )

    def normalize_symbol(self, symbol: str) -> str:
        return normalize_yahoo_symbol(symbol)

    def get_multiple_quotes(
        self, symbols: list[str]
    ) -> MarketBatchResult[MarketQuote]:
        """Consulta múltiples símbolos en paralelo."""
        unique = list(dict.fromkeys(symbols))
        result: MarketBatchResult[MarketQuote] = MarketBatchResult()
        if not unique:
            return result
        with ThreadPoolExecutor(
            max_workers=min(self.max_workers, len(unique))
        ) as executor:
            futures = {
                executor.submit(self.get_quote, symbol): symbol for symbol in unique
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    result.successes[symbol] = future.result()
                except Exception as exc:
                    result.errors[symbol] = type(exc).__name__
        return result

    def get_history(self, symbol: str, start: date, end: date) -> list[MarketBar]:
        normalized = normalize_yahoo_symbol(symbol)
        if end < start:
            raise ValueError("La fecha final no puede ser anterior a la inicial.")
        try:
            ticker = self.client.Ticker(normalized)
            frame = ticker.history(
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                auto_adjust=False,
                actions=True,
            )
        except Exception as exc:
            raise MarketProviderError(
                f"No fue posible descargar el histórico de {normalized}."
            ) from exc
        if frame is None or frame.empty:
            # Una consulta válida puede corresponder a una sesión sin observación.
            # HistoryService persiste esas fechas como NO_DATA para no reintentarlas.
            return []
        frame = self._normalize_columns(frame, normalized)
        required = {"Open", "High", "Low", "Close"}
        missing = required - set(frame.columns)
        if missing:
            raise MarketProviderError(
                f"Yahoo no devolvió columnas requeridas para {normalized}: "
                + ", ".join(sorted(missing))
            )
        timezone = str(getattr(frame.index, "tz", "") or "America/Mexico_City")
        bars: list[MarketBar] = []
        for index, row in frame.iterrows():
            required_values = [row["Open"], row["High"], row["Low"], row["Close"]]
            if any(pd.isna(value) for value in required_values):
                continue
            adjusted = row.get("Adj Close", row["Close"])
            if pd.isna(adjusted):
                adjusted = row["Close"]
            raw_volume = row.get("Volume", 0)
            volume = 0 if pd.isna(raw_volume) else int(raw_volume)
            bars.append(
                MarketBar(
                    symbol=normalized,
                    date=index.date(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    adj_close=float(adjusted),
                    volume=volume,
                    dividends=self._optional_number(row.get("Dividends", 0)),
                    stock_splits=self._optional_number(
                        row.get("Stock Splits", 0)
                    ),
                    timezone=timezone,
                    provider=self.provider_name,
                )
            )
        if not bars:
            raise MarketProviderError(
                f"Yahoo no devolvió filas válidas para {normalized}."
            )
        return bars

    def get_multiple_history(
        self, symbols: list[str], start: date, end: date
    ) -> MarketBatchResult[list[MarketBar]]:
        """Descarga varios históricos en paralelo."""
        unique = list(dict.fromkeys(symbols))
        result: MarketBatchResult[list[MarketBar]] = MarketBatchResult()
        if not unique:
            return result
        with ThreadPoolExecutor(
            max_workers=min(self.max_workers, len(unique))
        ) as executor:
            futures = {
                executor.submit(self.get_history, symbol, start, end): symbol
                for symbol in unique
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    result.successes[symbol] = future.result()
                except Exception as exc:
                    result.errors[symbol] = type(exc).__name__
        return result

    @staticmethod
    def _normalize_columns(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
        if not isinstance(frame.columns, pd.MultiIndex):
            return frame
        for level in range(frame.columns.nlevels):
            if symbol in frame.columns.get_level_values(level):
                return frame.xs(symbol, axis=1, level=level)
        if len(set(frame.columns.get_level_values(-1))) == 1:
            normalized = frame.copy()
            normalized.columns = normalized.columns.droplevel(-1)
            return normalized
        raise MarketProviderError(
            f"No fue posible interpretar columnas múltiples para {symbol}."
        )

    @staticmethod
    def _optional_number(value: object) -> float:
        return 0.0 if pd.isna(value) else float(str(value))
