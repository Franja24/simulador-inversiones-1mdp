"""Registro transaccional de compras y ventas."""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from config.settings import Settings, get_settings
from database.models import PortfolioModel, TransactionModel, TransactionType
from domain.transaction import TransactionCreate
from repositories.price_repository import PriceSource
from repositories.transaction_repository import TransactionRepository
from services.audit_service import AuditService
from services.portfolio_service import PortfolioService
from utils.dates import as_utc
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

    def validate_transaction_date(
        self, data: TransactionCreate, portfolio: PortfolioModel | None = None
    ) -> None:
        """Aplica las fechas del reto y rechaza operaciones futuras."""
        target = portfolio or self.portfolios.get_required(data.portfolio_id)
        transaction_time = as_utc(data.transaction_date)
        if transaction_time > datetime.now(UTC):
            raise BusinessRuleError("La fecha de la operación no puede ser futura.")
        transaction_date = data.transaction_date.date()
        if (
            target.challenge_start_date is not None
            and transaction_date < target.challenge_start_date
        ):
            raise BusinessRuleError(
                "La operación no puede ser anterior al inicio del reto."
            )
        if (
            target.challenge_end_date is not None
            and transaction_date > target.challenge_end_date
        ):
            raise BusinessRuleError(
                "La operación no puede ser posterior al final del reto."
            )

    def register(
        self, data: TransactionCreate, *, commit: bool = True
    ) -> tuple[TransactionModel, list[str]]:
        """Registra, recalcula y audita una operación.

        Con ``commit=False`` deja la transacción pendiente bajo control del caller.
        Si falla con ``commit=True``, revierte todas las mutaciones de esta operación.
        """
        try:
            portfolio = self.portfolios.get_required(data.portfolio_id)
            self.validate_transaction_date(data, portfolio)
            gross = data.quantity * data.price
            fees = data.commission + data.taxes
            total = (
                gross + fees
                if data.transaction_type == TransactionType.BUY
                else gross - fees
            ).quantize(MONEY, rounding=ROUND_HALF_UP)
            warnings: list[str] = []
            if data.transaction_type == TransactionType.BUY:
                if total > portfolio.available_cash:
                    raise BusinessRuleError(
                        "Efectivo insuficiente para completar la compra."
                    )
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
                projected_position = current_position_value + gross
                projected_total = valuation["total"]
                projected_weight = (
                    projected_position / projected_total
                    if projected_total > 0
                    else Decimal("1")
                )
                if projected_weight > Decimal(
                    str(self.settings.max_position_weight)
                ):
                    warnings.append(
                        "La compra supera el límite configurado por emisora."
                    )
                portfolio.available_cash -= total
            else:
                positions = {
                    position.symbol: position
                    for position in self.portfolios.calculate_positions(
                        data.portfolio_id, self.prices
                    )
                }
                held = positions.get(data.symbol)
                if held is None or data.quantity > held.total_quantity:
                    raise BusinessRuleError(
                        "No hay títulos suficientes para completar la venta."
                    )
                portfolio.available_cash += total

            transaction = TransactionModel(
                **data.model_dump(),
                total_amount=total,
            )
            self.transactions.add(transaction)
            self.session.flush()
            portfolio.current_value = self.portfolios.valuation(
                data.portfolio_id, self.prices
            )["total"]
            AuditService(self.session).record(
                portfolio.id,
                "TRANSACTION_CREATED",
                {
                    "type": data.transaction_type.value,
                    "symbol": data.symbol,
                    "total": str(total),
                },
            )
            if commit:
                self.session.commit()
            return transaction, warnings
        except Exception:
            if commit:
                self.session.rollback()
            raise
