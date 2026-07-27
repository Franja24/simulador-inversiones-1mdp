"""Adaptador de Yahoo Finance mediante yfinance."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from domain.market import MarketBar, MarketQuote
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

    def __init__(self, client: Any | None = None) -> None:
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
        if price <= 0:
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

    def get_multiple_quotes(self, symbols: list[str]) -> dict[str, MarketQuote]:
        """Consulta múltiples símbolos en paralelo."""
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(symbols)))) as executor:
            quotes = executor.map(self.get_quote, symbols)
            return dict(zip(symbols, quotes, strict=True))

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
            raise MarketProviderError(f"No existen datos históricos para {normalized}.")
        timezone = str(getattr(frame.index, "tz", "") or "America/Mexico_City")
        bars: list[MarketBar] = []
        for index, row in frame.iterrows():
            bars.append(
                MarketBar(
                    symbol=normalized,
                    date=index.date(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    adj_close=float(row.get("Adj Close", row["Close"])),
                    volume=int(row.get("Volume", 0)),
                    dividends=float(row.get("Dividends", 0)),
                    stock_splits=float(row.get("Stock Splits", 0)),
                    timezone=timezone,
                    provider=self.provider_name,
                )
            )
        return bars

    def get_multiple_history(
        self, symbols: list[str], start: date, end: date
    ) -> dict[str, list[MarketBar]]:
        """Descarga varios históricos en paralelo."""
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(symbols)))) as executor:
            histories = executor.map(
                lambda symbol: self.get_history(symbol, start, end), symbols
            )
            return dict(zip(symbols, histories, strict=True))

    def is_market_open(self) -> bool:
        now = datetime.now(ZoneInfo("America/Mexico_City"))
        return now.weekday() < 5 and time(8, 30) <= now.time() <= time(15, 0)
