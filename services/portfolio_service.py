"""Creación y valoración de portafolios."""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from database.models import PortfolioModel, TransactionType
from domain.portfolio import PortfolioCreate
from domain.position import Position
from repositories.portfolio_repository import PortfolioRepository
from repositories.price_repository import PriceSource
from repositories.transaction_repository import TransactionRepository
from utils.calculations import percentage_change
from utils.validators import BusinessRuleError


class PortfolioService:
    """Orquesta cálculos derivados del historial de operaciones."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.portfolios = PortfolioRepository(session)
        self.transactions = TransactionRepository(session)

    def create(self, data: PortfolioCreate) -> PortfolioModel:
        """Crea un portafolio cuyo efectivo coincide con el capital inicial."""
        portfolio = PortfolioModel(
            name=data.name,
            initial_capital=data.initial_capital,
            available_cash=data.initial_capital,
            current_value=data.initial_capital,
            challenge_start_date=data.challenge_start_date,
            challenge_end_date=data.challenge_end_date,
            benchmark_symbol=data.benchmark_symbol,
            notes=data.notes,
        )
        self.portfolios.add(portfolio)
        self.session.commit()
        return portfolio

    def get_required(self, portfolio_id: int) -> PortfolioModel:
        """Obtiene un portafolio o produce un error claro."""
        portfolio = self.portfolios.get(portfolio_id)
        if portfolio is None:
            raise BusinessRuleError("El portafolio no existe.")
        return portfolio

    def calculate_positions(
        self, portfolio_id: int, prices: PriceSource | None = None
    ) -> list[Position]:
        """Reconstruye posiciones usando costo promedio ponderado.

        Las ventas reducen cantidad y costo al promedio vigente. Las comisiones
        de compra forman parte del costo; las de venta afectan la utilidad realizada.
        """
        records = self.transactions.list_for_portfolio(portfolio_id)
        lots: dict[str, dict[str, object]] = {}
        for item in records:
            state = lots.setdefault(
                item.symbol,
                {
                    "quantity": Decimal("0"),
                    "cost": Decimal("0"),
                    "name": item.company_name,
                    "stop_loss": None,
                    "take_profit": None,
                },
            )
            quantity = Decimal(str(state["quantity"]))
            cost = Decimal(str(state["cost"]))
            if item.transaction_type == TransactionType.BUY:
                state["quantity"] = quantity + item.quantity
                state["cost"] = cost + item.quantity * item.price + item.commission + item.taxes
                state["name"] = item.company_name or state["name"]
                state["stop_loss"] = item.stop_loss or state["stop_loss"]
                state["take_profit"] = item.take_profit or state["take_profit"]
            elif item.transaction_type == TransactionType.SELL and quantity:
                average = cost / quantity
                state["quantity"] = quantity - item.quantity
                state["cost"] = cost - average * item.quantity

        portfolio = self.get_required(portfolio_id)
        now = datetime.now(UTC)
        preliminary: list[tuple[str, dict[str, object], Decimal, Decimal]] = []
        market_total = Decimal("0")
        for symbol, state in lots.items():
            quantity = Decimal(str(state["quantity"]))
            if quantity <= 0:
                continue
            cost = Decimal(str(state["cost"]))
            current = prices.get(symbol) if prices else None
            current = current if current is not None else cost / quantity
            market = quantity * current
            market_total += market
            preliminary.append((symbol, state, current, market))
        total_value = portfolio.available_cash + market_total
        return [
            Position(
                symbol=symbol,
                company_name=state["name"] if isinstance(state["name"], str) else None,
                total_quantity=Decimal(str(state["quantity"])),
                average_purchase_price=Decimal(str(state["cost"]))
                / Decimal(str(state["quantity"])),
                current_price=current,
                invested_amount=Decimal(str(state["cost"])),
                current_market_value=market,
                unrealized_profit_loss=market - Decimal(str(state["cost"])),
                unrealized_return_percentage=percentage_change(
                    market, Decimal(str(state["cost"]))
                ),
                portfolio_weight=(
                    market / total_value * Decimal("100") if total_value else Decimal("0")
                ),
                stop_loss=(
                    Decimal(str(state["stop_loss"])) if state["stop_loss"] is not None else None
                ),
                take_profit=(
                    Decimal(str(state["take_profit"]))
                    if state["take_profit"] is not None
                    else None
                ),
                last_updated=now,
                last_price_date=prices.get_last_update_time(symbol) if prices else None,
            )
            for symbol, state, current, market in preliminary
        ]

    def realized_profit_loss(self, portfolio_id: int) -> Decimal:
        """Calcula utilidad realizada mediante costo promedio ponderado."""
        states: dict[str, tuple[Decimal, Decimal]] = {}
        realized = Decimal("0")
        for item in self.transactions.list_for_portfolio(portfolio_id):
            quantity, cost = states.get(item.symbol, (Decimal("0"), Decimal("0")))
            if item.transaction_type == TransactionType.BUY:
                states[item.symbol] = (
                    quantity + item.quantity,
                    cost + item.quantity * item.price + item.commission + item.taxes,
                )
            elif item.transaction_type == TransactionType.SELL:
                average = cost / quantity
                realized += (
                    item.quantity * item.price
                    - item.commission
                    - item.taxes
                    - item.quantity * average
                )
                states[item.symbol] = (
                    quantity - item.quantity,
                    cost - item.quantity * average,
                )
        return realized

    def valuation(
        self, portfolio_id: int, prices: PriceSource | None = None
    ) -> dict[str, Decimal]:
        """Calcula la valoración vigente y actúa como fuente principal.

        ``Portfolio.current_value`` se conserva como caché compatible con Fase 1,
        pero no sustituye este cálculo cuando existen precios disponibles.
        """
        portfolio = self.get_required(portfolio_id)
        positions = self.calculate_positions(portfolio_id, prices)
        invested = sum((p.current_market_value for p in positions), Decimal("0"))
        total = portfolio.available_cash + invested
        unrealized = sum((p.unrealized_profit_loss for p in positions), Decimal("0"))
        realized = self.realized_profit_loss(portfolio_id)
        return {
            "cash": portfolio.available_cash,
            "invested": invested,
            "total": total,
            "realized": realized,
            "unrealized": unrealized,
            "profit_loss": total - portfolio.initial_capital,
            "return_percentage": percentage_change(total, portfolio.initial_capital),
        }
