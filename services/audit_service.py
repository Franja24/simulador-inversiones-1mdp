"""Registro centralizado de auditoría sin información sensible."""

import json

from sqlalchemy.orm import Session

from database.models import AuditLogModel


class AuditService:
    """Crea eventos de auditoría dentro de la transacción del caller."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self, portfolio_id: int | None, action: str, details: dict[str, object]
    ) -> None:
        """Agrega un evento compacto y fuerza su persistencia pendiente."""
        self.session.add(
            AuditLogModel(
                portfolio_id=portfolio_id,
                action=action,
                details=json.dumps(details, ensure_ascii=False, default=str),
            )
        )
        self.session.flush()

