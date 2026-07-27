"""Registro transaccional de compras y ventas."""

import json
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from config.settings import Settings, get_settings
from database.models import AuditLogModel, TransactionModel, TransactionType
from domain.transaction import TransactionCreate
from repositories.price_repository import PriceSource
from repositories.transaction_repository import TransactionRepository
from services.portfolio_service import PortfolioService
from utils.validators import BusinessRuleError

MONEY = Decimal("0.01")


class TransactionService:
    """Valida y persiste operaciones de forma atómica."""

    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        prices: PriceSource | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.portfolios = PortfolioService(session)
        self.transactions = TransactionRepository(session)
        self.prices = prices

    def register(
        self, data: TransactionCreate, *, commit: bool = True
    ) -> tuple[TransactionModel, list[str]]:
        """Registra una operación y devuelve advertencias no bloqueantes."""
        portfolio = self.portfolios.get_required(data.portfolio_id)
        gross = data.quantity * data.price
        fees = data.commission + data.taxes
        total = (gross + fees if data.transaction_type == TransactionType.BUY else gross - fees)
        total = total.quantize(MONEY, rounding=ROUND_HALF_UP)
        warnings: list[str] = []
        if data.transaction_type == TransactionType.BUY:
            if total > portfolio.available_cash:
                raise BusinessRuleError("Efectivo insuficiente para completar la compra.")
            valuation = self.portfolios.valuation(data.portfolio_id, self.prices)
            positions = {
                position.symbol: position
                for position in self.portfolios.calculate_positions(
                    data.portfolio_id, self.prices
                )
            }
            current_position_value = (
                positions[data.symbol].current_market_value
                if data.symbol in positions
                else Decimal("0")
            )
            projected_position = current_position_value + total
            projected_total = valuation["total"]
            projected_weight = (
                projected_position / projected_total
                if projected_total
                else Decimal("1")
            )
            if projected_weight > Decimal(str(self.settings.max_position_weight)):
                warnings.append("La compra supera el límite configurado por emisora.")
            portfolio.available_cash -= total
        else:
            positions = {
                p.symbol: p
                for p in self.portfolios.calculate_positions(data.portfolio_id)
            }
            held = positions.get(data.symbol)
            if held is None or data.quantity > held.total_quantity:
                raise BusinessRuleError("No hay títulos suficientes para completar la venta.")
            portfolio.available_cash += total

        transaction = TransactionModel(
            **data.model_dump(),
            total_amount=total,
        )
        self.transactions.add(transaction)
        portfolio.current_value = self.portfolios.valuation(
            data.portfolio_id, self.prices
        )["total"]
        self.session.add(
            AuditLogModel(
                portfolio_id=portfolio.id,
                action="TRANSACTION_CREATED",
                details=json.dumps(
                    {
                        "type": data.transaction_type.value,
                        "symbol": data.symbol,
                        "total": str(total),
                    }
                ),
            )
        )
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return transaction, warnings
