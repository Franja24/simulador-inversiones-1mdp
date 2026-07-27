"""Configuración segura de logs locales."""

import logging
from pathlib import Path

from config.settings import get_settings


def configure_logging() -> None:
    """Configura archivo y consola sin registrar secretos."""
    Path("data").mkdir(exist_ok=True)
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler("data/app.log", encoding="utf-8"), logging.StreamHandler()],
        force=True,
    )

