"""Inicialización idempotente del esquema."""

from sqlalchemy import inspect, text

from database import models  # noqa: F401
from database.connection import Base, engine


def initialize_database() -> None:
    """Crea las tablas que todavía no existen."""
    Base.metadata.create_all(bind=engine)
    columns = {
        item["name"] for item in inspect(engine).get_columns("indicator_cache")
    }
    additions = {
        "history_row_count": "INTEGER NOT NULL DEFAULT 0",
        "history_version": "VARCHAR(64) NOT NULL DEFAULT ''",
        "indicator_version": "VARCHAR(20) NOT NULL DEFAULT '1'",
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(
                    text(f"ALTER TABLE indicator_cache ADD COLUMN {name} {definition}")
                )


if __name__ == "__main__":
    initialize_database()
    print("Base de datos inicializada.")
