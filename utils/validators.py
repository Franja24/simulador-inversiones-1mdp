"""Excepciones de validación de negocio."""


class BusinessRuleError(ValueError):
    """Indica que una operación incumple una regla del portafolio."""

