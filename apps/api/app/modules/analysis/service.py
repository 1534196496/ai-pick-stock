"""协调历史数据刷新、指标计算、模型调用与最近报告缓存。"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.analysis.dataset import build_fund_dataset, build_stock_dataset
from app.modules.analysis.prompt import build_analysis_prompts
from app.modules.analysis.provider import (
    AIModelClient,
    AIProviderAuthenticationError,
    AIProviderPayloadError,
    AIProviderUnavailableError,
)
from app.modules.analysis.repository import AnalysisRepository
from app.modules.analysis.schemas import (
    AIAnalysisResponse,
    AnalysisInstrumentResponse,
    AnalysisMetricResponse,
    GeneratedAnalysis,
)
from app.modules.instruments.domain import InstrumentRecord
from app.modules.instruments.enums import AssetType
from app.modules.market_data.providers.contracts import FundNavProvider, StockPriceProvider
from app.modules.market_data.providers.http import ProviderPayloadError, ProviderUnavailableError
from app.modules.market_data.providers.schemas import StockQuoteRequest
from app.modules.market_data.repository import MarketDataRepository

_HISTORY_LIMIT = 250
_MINIMUM_HISTORY = 60


@dataclass(frozen=True, slots=True)
class AnalysisError(Exception):
    """保存可稳定映射到 HTTP 的分析业务错误。"""

    status_code: int
    code: str
    message: str


class AIAnalysisService:
    """为股票和基金生成口径不同、可追溯的研究报告。"""

    def __init__(
        self,
        repository: AnalysisRepository,
        market_data_repository: MarketDataRepository,
        stock_provider: StockPriceProvider,
        fund_provider: FundNavProvider,
        ai_client: AIModelClient | None,
    ) -> None:
        """注入请求事务、真实行情来源和可选全站模型客户端。"""
        self._repository = repository
        self._market_data = market_data_repository
        self._stock_provider = stock_provider
        self._fund_provider = fund_provider
        self._ai_client = ai_client

    async def get_latest_report(
        self,
        *,
        user_id: UUID,
        instrument_id: UUID,
    ) -> AIAnalysisResponse | None:
        """返回用户已保存的最近报告；尚无报告时返回空且不调用模型。"""
        instrument = await self._require_tracked_instrument(
            user_id=user_id,
            instrument_id=instrument_id,
        )
        report = await self._repository.latest_report(
            user_id=user_id,
            instrument_id=instrument_id,
        )
        if report is None:
            return None
        return _response(report, instrument)

    async def generate_report(
        self,
        *,
        user_id: UUID,
        instrument_id: UUID,
    ) -> AIAnalysisResponse:
        """刷新真实历史数据、调用模型并覆盖最近报告。"""
        if self._ai_client is None:
            raise AnalysisError(503, "AI_NOT_CONFIGURED", "服务器尚未配置 AI 模型")
        instrument = await self._require_tracked_instrument(
            user_id=user_id,
            instrument_id=instrument_id,
        )
        holding = await self._repository.holding_context(
            user_id=user_id,
            instrument_id=instrument_id,
        )
        if instrument.asset_type is AssetType.STOCK:
            await self._refresh_stock_history(instrument)
            bars = await self._market_data.stock_daily_bars(
                instrument_id=instrument.id,
                limit=_HISTORY_LIMIT,
            )
            if len(bars) < _MINIMUM_HISTORY:
                raise AnalysisError(
                    422, "ANALYSIS_DATA_INSUFFICIENT", "股票历史数据不足 60 个交易日"
                )
            dataset = build_stock_dataset(bars, holding=holding)
        else:
            await self._refresh_fund_history(instrument)
            navs = await self._market_data.fund_daily_navs(
                instrument_id=instrument.id,
                limit=_HISTORY_LIMIT,
            )
            if len(navs) < _MINIMUM_HISTORY:
                raise AnalysisError(
                    422, "ANALYSIS_DATA_INSUFFICIENT", "基金净值历史不足 60 个交易日"
                )
            dataset = build_fund_dataset(navs, holding=holding)

        system_prompt, user_prompt = build_analysis_prompts(dataset.prompt_context(instrument))
        try:
            content = await self._ai_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except AIProviderAuthenticationError as error:
            raise AnalysisError(503, "AI_AUTHENTICATION_FAILED", "AI 模型配置无效") from error
        except AIProviderUnavailableError as error:
            raise AnalysisError(
                503, "AI_PROVIDER_UNAVAILABLE", "AI 模型暂时不可用，请稍后重试"
            ) from error
        except AIProviderPayloadError as error:
            raise AnalysisError(
                502, "AI_RESPONSE_INVALID", "AI 返回内容不完整，请重新生成"
            ) from error
        report = await self._repository.save_report(
            user_id=user_id,
            instrument_id=instrument_id,
            provider=self._ai_client.provider,
            model=self._ai_client.model,
            dataset=dataset,
            content=content,
        )
        return _response(report, instrument)

    async def _require_tracked_instrument(
        self,
        *,
        user_id: UUID,
        instrument_id: UUID,
    ) -> InstrumentRecord:
        """拒绝分析不属于当前用户持仓或自选的标的。"""
        instrument = await self._repository.get_tracked_instrument(
            user_id=user_id,
            instrument_id=instrument_id,
        )
        if instrument is None:
            raise AnalysisError(404, "INSTRUMENT_NOT_TRACKED", "该标的不在你的持仓或自选中")
        return instrument

    async def _refresh_stock_history(self, instrument: InstrumentRecord) -> None:
        """尽力刷新股票日线；来源异常时允许使用已有本地历史。"""
        try:
            snapshots = await self._stock_provider.fetch_stock_daily_bars(
                StockQuoteRequest(ticker=instrument.ticker, exchange=instrument.exchange),
                limit=_HISTORY_LIMIT,
            )
            await self._market_data.upsert_stock_daily_bars(
                instrument_id=instrument.id,
                snapshots=snapshots,
            )
        except (ProviderUnavailableError, ProviderPayloadError):
            return

    async def _refresh_fund_history(self, instrument: InstrumentRecord) -> None:
        """尽力刷新官方基金净值；来源异常时允许使用已有本地历史。"""
        try:
            snapshots = await self._fund_provider.fetch_official_nav_history(
                instrument.ticker,
                limit=_HISTORY_LIMIT,
            )
            await self._market_data.upsert_official_navs(snapshots)
        except (ProviderUnavailableError, ProviderPayloadError):
            return


def _response(report: object, instrument: InstrumentRecord) -> AIAnalysisResponse:
    """把已持久化报告转换为稳定公开响应。"""
    from app.modules.analysis.models import AIAnalysisReport

    if not isinstance(report, AIAnalysisReport):
        raise TypeError("报告类型异常")
    content = GeneratedAnalysis.model_validate(report.content)
    return AIAnalysisResponse(
        id=report.id,
        instrument=AnalysisInstrumentResponse(
            id=instrument.id,
            asset_type=instrument.asset_type,
            market=instrument.market,
            exchange=instrument.exchange,
            ticker=instrument.ticker,
            name=instrument.name,
            currency=instrument.currency,
        ),
        provider=report.provider,
        model=report.model,
        data_as_of=report.data_as_of,
        data_sources=list(report.data_sources),
        metrics=[AnalysisMetricResponse.model_validate(item) for item in report.metrics],
        conclusion=content.conclusion,
        summary=content.summary,
        highlights=content.highlights,
        risks=content.risks,
        actions=content.actions,
        generated_at=report.generated_at,
    )
