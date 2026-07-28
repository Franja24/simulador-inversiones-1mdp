"""Escenarios adversos explicables sin afirmar repetición futura."""

from config.simulation import ChallengeRulesConfig
from domain.simulation import StressScenarioResult


class StressTestService:
    PREDEFINED = {
        "market_-5": -0.05,
        "market_-10": -0.10,
        "market_-15": -0.15,
        "main_position_-20": -0.20,
        "adverse_combination": -0.25,
    }

    def run_custom_scenario(
        self,
        weights: dict[str, float],
        shocks: dict[str, float],
        name: str,
        rules: ChallengeRulesConfig | None = None,
    ) -> StressScenarioResult:
        impacts = {
            symbol: weight * shocks.get(symbol, 0)
            for symbol, weight in weights.items()
        }
        total = sum(impacts.values())
        damaged = {
            symbol: max(0, weight * (1 + shocks.get(symbol, 0)))
            for symbol, weight in weights.items()
        }
        denominator = sum(damaged.values())
        normalized = {
            symbol: value / denominator if denominator else 0
            for symbol, value in damaged.items()
        }
        violations: list[str] = []
        if rules is not None:
            violations = [
                f"{symbol} supera peso máximo"
                for symbol, value in normalized.items()
                if value > rules.maximum_symbol_weight
            ]
        damage = abs(total)
        contributions = {
            symbol: abs(value) / damage if damage else 0
            for symbol, value in impacts.items()
        }
        return StressScenarioResult(
            name=name,
            asset_impacts=impacts,
            portfolio_impact=total,
            total_loss=max(0, -total),
            new_concentration=sum(value**2 for value in normalized.values()),
            damage_contribution=contributions,
            rule_violations=violations,
            warnings=["El escenario es hipotético; no implica que vaya a repetirse."],
        )

    def run_predefined(
        self, weights: dict[str, float], scenario: str
    ) -> StressScenarioResult:
        if scenario not in self.PREDEFINED:
            raise ValueError("Escenario no soportado.")
        shock = self.PREDEFINED[scenario]
        if scenario == "main_position_-20":
            main = max(weights, key=weights.get)  # type: ignore[arg-type]
            shocks = {main: shock}
        else:
            shocks = dict.fromkeys(weights, shock)
        return self.run_custom_scenario(weights, shocks, scenario)

    def run_factor_shocks(
        self, weights: dict[str, float], market_shock: float, volatility_multiplier: float
    ) -> StressScenarioResult:
        adjusted = market_shock * max(1, volatility_multiplier)
        return self.run_custom_scenario(
            weights, dict.fromkeys(weights, adjusted), "factor_shock"
        )

