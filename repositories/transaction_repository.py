"""Acceso a datos de operaciones."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import TransactionModel


class TransactionRepository:
    """Persistencia y consulta de operaciones."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, transaction: TransactionModel) -> TransactionModel:
        """Agrega una operación."""
        self.session.add(transaction)
        self.session.flush()
        return transaction

    def list_for_portfolio(self, portfolio_id: int) -> list[TransactionModel]:
        """Devuelve el historial en orden cronológico estable."""
        statement = (
            select(TransactionModel)
            .where(TransactionModel.portfolio_id == portfolio_id)
            .order_by(TransactionModel.transaction_date, TransactionModel.id)
        )
        return list(self.session.scalars(statement))

