"""Persistencia versionada del universo, AQS, régimen y backtests."""

import json
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from config.quant_score import QuantScoreConfig
from database.models import (
    BacktestRunModel,
    MarketRegimeSnapshotModel,
    QuantScoreComponentModel,
    QuantScoreConfigModel,
    QuantScoreResultModel,
    QuantScoreRunModel,
    QuantUniverseModel,
)
from domain.quant import (
    BacktestResult,
    MarketRegimeResult,
    QuantScoreResult,
    ScoreComponent,
)


class QuantUniverseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(
        self,
        symbol: str,
        company_name: str | None = None,
        sector: str | None = None,
        *,
        active: bool = True,
        minimum_liquidity: float | None = None,
    ) -> QuantUniverseModel:
        normalized = symbol.strip().upper()
        model = self.session.get(QuantUniverseModel, normalized)
        if model is None:
            model = QuantUniverseModel(symbol=normalized)
            self.session.add(model)
        model.company_name = company_name
        model.sector = sector
        model.active = active
        model.minimum_liquidity = minimum_liquidity
        self.session.flush()
        return model

    def list_active(self) -> list[QuantUniverseModel]:
        return list(
            self.session.scalars(
                select(QuantUniverseModel)
                .where(QuantUniverseModel.active.is_(True))
                .order_by(QuantUniverseModel.symbol)
            )
        )


class QuantRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_config(self, config: QuantScoreConfig) -> None:
        model = self.session.get(QuantScoreConfigModel, config.model_version)
        payload = config.model_dump_json()
        if model is None:
            self.session.add(
                QuantScoreConfigModel(
                    model_version=config.model_version, payload=payload
                )
            )
        elif model.payload != payload:
            raise ValueError("Una versión existente no puede cambiar de configuración.")

    def save_results(
        self,
        results: list[QuantScoreResult],
        config: QuantScoreConfig,
        *,
        force: bool = False,
    ) -> None:
        if not results:
            return
        self.save_config(config)
        first = results[0]
        run = QuantScoreRunModel(
            effective_date=first.effective_date,
            model_version=config.model_version,
            benchmark_symbol=first.benchmark_symbol,
            universe_json=json.dumps([item.symbol for item in results]),
            config_json=config.model_dump_json(),
        )
        self.session.add(run)
        self.session.flush()
        for result in results:
            existing = self._result_model(
                result.symbol, result.effective_date, result.model_version
            )
            if existing is not None:
                if not force:
                    continue
                self.session.execute(
                    delete(QuantScoreComponentModel).where(
                        QuantScoreComponentModel.result_id == existing.id
                    )
                )
                self.session.delete(existing)
                self.session.flush()
            model = QuantScoreResultModel(
                run_id=run.id,
                symbol=result.symbol,
                effective_date=result.effective_date,
                model_version=result.model_version,
                benchmark_symbol=result.benchmark_symbol,
                market_regime=result.market_regime,
                base_score=result.base_score,
                regime_adjustment=result.regime_adjustment,
                total_score=result.total_score,
                confidence=result.confidence,
                classification=result.classification,
                warnings_json=json.dumps(result.warnings, ensure_ascii=False),
                diagnostics_json="{}",
            )
            self.session.add(model)
            self.session.flush()
            self.session.add_all(
                [
                    QuantScoreComponentModel(result_id=model.id, **item.model_dump())
                    for item in result.components
                ]
            )

    def load_result(
        self, symbol: str, effective_date: date, model_version: str
    ) -> QuantScoreResult | None:
        model = self._result_model(symbol, effective_date, model_version)
        if model is None:
            return None
        components = list(
            self.session.scalars(
                select(QuantScoreComponentModel)
                .where(QuantScoreComponentModel.result_id == model.id)
                .order_by(QuantScoreComponentModel.id)
            )
        )
        return QuantScoreResult(
            symbol=model.symbol,
            effective_date=model.effective_date,
            base_score=model.base_score,
            regime_adjustment=model.regime_adjustment,
            total_score=model.total_score,
            classification=model.classification,
            confidence=model.confidence,
            components=[
                ScoreComponent(
                    name=item.name,
                    raw_value=item.raw_value,
                    normalized_score=item.normalized_score,
                    weight=item.weight,
                    weighted_score=item.weighted_score,
                    explanation=item.explanation,
                    data_available=item.data_available,
                )
                for item in components
            ],
            warnings=json.loads(model.warnings_json),
            model_version=model.model_version,
            benchmark_symbol=model.benchmark_symbol,
            market_regime=model.market_regime,
        )

    def previous_results(
        self, effective_date: date, model_version: str
    ) -> list[QuantScoreResultModel]:
        prior = self.session.scalar(
            select(QuantScoreResultModel.effective_date)
            .where(
                QuantScoreResultModel.effective_date < effective_date,
                QuantScoreResultModel.model_version == model_version,
            )
            .order_by(QuantScoreResultModel.effective_date.desc())
            .limit(1)
        )
        if prior is None:
            return []
        return list(
            self.session.scalars(
                select(QuantScoreResultModel).where(
                    QuantScoreResultModel.effective_date == prior,
                    QuantScoreResultModel.model_version == model_version,
                )
            )
        )

    def save_regime(
        self, result: MarketRegimeResult, model_version: str, *, force: bool = False
    ) -> None:
        existing = self.session.scalar(
            select(MarketRegimeSnapshotModel).where(
                MarketRegimeSnapshotModel.benchmark_symbol
                == result.benchmark_symbol,
                MarketRegimeSnapshotModel.effective_date == result.effective_date,
                MarketRegimeSnapshotModel.model_version == model_version,
            )
        )
        if existing is not None and not force:
            return
        if existing is not None:
            self.session.delete(existing)
            self.session.flush()
        self.session.add(
            MarketRegimeSnapshotModel(
                benchmark_symbol=result.benchmark_symbol,
                effective_date=result.effective_date,
                model_version=model_version,
                primary_regime=result.primary_regime,
                high_volatility=result.high_volatility,
                confidence=result.confidence,
                metrics_json=json.dumps(result.metrics),
                warnings_json=json.dumps(result.warnings, ensure_ascii=False),
            )
        )

    def save_backtest(self, result: BacktestResult) -> None:
        self.session.merge(
            BacktestRunModel(
                run_id=result.run_id,
                model_version=result.model_version,
                start_date=result.start_date,
                end_date=result.end_date,
                benchmark_symbol=result.benchmark_symbol,
                config_json=json.dumps(result.configuration),
                result_json=result.model_dump_json(),
            )
        )

    def _result_model(
        self, symbol: str, effective_date: date, model_version: str
    ) -> QuantScoreResultModel | None:
        return self.session.scalar(
            select(QuantScoreResultModel).where(
                QuantScoreResultModel.symbol == symbol.strip().upper(),
                QuantScoreResultModel.effective_date == effective_date,
                QuantScoreResultModel.model_version == model_version,
            )
        )
