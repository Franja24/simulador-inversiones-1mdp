"""Validación configurable de reglas del reto para candidatos."""

from config.simulation import ChallengeRulesConfig


class ChallengeRulesService:
    @staticmethod
    def validate_portfolio(
        weights: dict[str, float],
        cash_weight: float,
        config: ChallengeRulesConfig,
    ) -> list[str]:
        violations: list[str] = []
        active = {key: value for key, value in weights.items() if value > 0}
        if len(active) < config.minimum_symbols:
            violations.append("Número de emisoras inferior al mínimo.")
        if len(active) > config.maximum_symbols:
            violations.append("Número de emisoras superior al máximo.")
        if any(value < 0 for value in weights.values()):
            violations.append("No se permiten posiciones negativas.")
        if any(value > config.maximum_symbol_weight for value in weights.values()):
            violations.append("Una posición supera el máximo permitido.")
        if not config.allow_cash and cash_weight > 1e-9:
            violations.append("El efectivo no está permitido.")
        if cash_weight > config.maximum_cash_weight:
            violations.append("El efectivo supera el máximo.")
        if not config.leverage_allowed and sum(weights.values()) + cash_weight > 1 + 1e-9:
            violations.append("El apalancamiento no está permitido.")
        allowed = {item.upper() for item in config.allowed_symbols}
        excluded = {item.upper() for item in config.excluded_symbols}
        if allowed and any(item.upper() not in allowed for item in active):
            violations.append("El portafolio contiene símbolos no permitidos.")
        if any(item.upper() in excluded for item in active):
            violations.append("El portafolio contiene símbolos excluidos.")
        return violations

    validate_candidate = validate_portfolio

    @staticmethod
    def explain_violations(violations: list[str]) -> str:
        return "Cumple todas las reglas." if not violations else " ".join(violations)

