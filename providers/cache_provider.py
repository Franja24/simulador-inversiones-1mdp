"""Proveedor offline respaldado por SQLite."""

from datetime import UTC, date, datetime

from domain.market import MarketBar, MarketQuote
from providers.market_provider import MarketProvider, MarketProviderError
from repositories.market_history_repository import MarketHistoryRepository


class CacheProvider(MarketProvider):
    """Expone históricos locales usando el mismo contrato de mercado."""

    def __init__(self, repository: MarketHistoryRepository) -> None:
        self.repository = repository

    @property
    def provider_name(self) -> str:
        return "cache"

    @property
    def provider_version(self) -> str:
        return "1"

    @property
    def supported_markets(self) -> tuple[str, ...]:
        return ("LOCAL",)

    def get_quote(self, symbol: str) -> MarketQuote:
        rows = self.repository.list_history(symbol)
        if not rows:
            raise MarketProviderError(f"No existe cache local para {symbol}.")
        latest = rows[-1]
        previous = rows[-2].close if len(rows) > 1 else None
        return MarketQuote(
            symbol=latest.symbol,
            price=latest.close,
            previous_close=previous,
            volume=latest.volume,
            timestamp=datetime.combine(latest.date, datetime.min.time(), tzinfo=UTC),
            timezone=latest.timezone,
            provider=self.provider_name,
        )

    def get_history(self, symbol: str, start: date, end: date) -> list[MarketBar]:
        return [
            MarketBar(
                symbol=item.symbol,
                date=item.date,
                open=item.open,
                high=item.high,
                low=item.low,
                close=item.close,
                adj_close=item.adj_close,
                volume=item.volume,
                dividends=item.dividends,
                stock_splits=item.stock_splits,
                timezone=item.timezone,
                provider=item.provider,
            )
            for item in self.repository.list_history(symbol, start, end)
        ]

    def is_market_open(self) -> bool:
        return False
