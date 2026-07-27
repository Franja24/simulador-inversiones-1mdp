"""Inicialización idempotente del esquema."""

from database import models  # noqa: F401
from database.connection import Base, engine


def initialize_database() -> None:
    """Crea las tablas que todavía no existen."""
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    initialize_database()
    print("Base de datos inicializada.")

