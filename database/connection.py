"""Motor, sesiones y base declarativa de SQLAlchemy."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from config.settings import get_settings


class Base(DeclarativeBase):
    """Clase base para modelos ORM."""


def build_engine(database_url: str | None = None) -> Engine:
    """Crea un motor adecuado para archivo SQLite o pruebas en memoria."""
    url = database_url or get_settings().database_url
    kwargs: dict[str, object] = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    if url == "sqlite://":
        kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    """Proporciona una sesión y garantiza su cierre."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
