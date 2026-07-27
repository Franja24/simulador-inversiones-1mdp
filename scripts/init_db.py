"""Inicializa la base y crea un portafolio demostrativo sin operaciones."""

from config.settings import get_settings
from database.connection import SessionLocal
from database.migrations import initialize_database
from domain.portfolio import PortfolioCreate
from repositories.portfolio_repository import PortfolioRepository
from services.portfolio_service import PortfolioService


def main() -> None:
    """Crea el esquema y datos iniciales de manera idempotente."""
    initialize_database()
    with SessionLocal() as session:
        if not PortfolioRepository(session).list_all():
            settings = get_settings()
            PortfolioService(session).create(
                PortfolioCreate(
                    name="Portafolio Reto Actinver",
                    initial_capital=settings.default_initial_capital,
                )
            )
            print("Portafolio de demostración creado.")
        else:
            print("La base ya contiene un portafolio.")


if __name__ == "__main__":
    main()

