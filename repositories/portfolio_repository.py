"""Acceso a datos de portafolios."""

from sqlalchemy.orm import Session

from database.models import PortfolioModel


class PortfolioRepository:
    """Persistencia de portafolios."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, portfolio: PortfolioModel) -> PortfolioModel:
        """Agrega y sincroniza una entidad."""
        self.session.add(portfolio)
        self.session.flush()
        return portfolio

    def get(self, portfolio_id: int) -> PortfolioModel | None:
        """Busca por identificador."""
        return self.session.get(PortfolioModel, portfolio_id)

    def list_all(self) -> list[PortfolioModel]:
        """Lista portafolios por identificador."""
        return list(self.session.query(PortfolioModel).order_by(PortfolioModel.id))

