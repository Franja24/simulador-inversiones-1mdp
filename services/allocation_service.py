"""Asignación equal-weight bajo límites explícitos de peso y efectivo."""

from domain.quant import AllocationResult


class RestrictedEqualWeightAllocator:
    @staticmethod
    def allocate(
        symbols: list[str],
        *,
        top_n: int,
        maximum_symbol_weight: float,
        allow_cash: bool,
    ) -> AllocationResult:
        selected = list(dict.fromkeys(symbols))[:top_n]
        if not selected:
            if not allow_cash:
                raise ValueError("No hay símbolos elegibles y el efectivo está prohibido.")
            return AllocationResult(
                weights={}, cash_weight=1.0, warnings=["Sin símbolos elegibles."]
            )
        capacity = len(selected) * maximum_symbol_weight
        if not allow_cash and capacity < 1 - 1e-12:
            raise ValueError(
                "No es posible asignar 100% con los símbolos elegibles y el "
                "maximum_symbol_weight configurado."
            )
        target = 1 / len(selected)
        weight = min(target, maximum_symbol_weight)
        weights = {symbol: weight for symbol in selected}
        cash = max(0.0, 1 - sum(weights.values()))
        warnings: list[str] = []
        if cash > 1e-12:
            warnings.append(f"Efectivo residual: {cash:.2%}.")
        return AllocationResult(
            weights=weights,
            cash_weight=round(cash, 12),
            warnings=warnings,
        )
