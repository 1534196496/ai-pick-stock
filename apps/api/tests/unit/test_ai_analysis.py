"""AI 协议适配和股票、基金指标数据集回归测试。"""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.modules.analysis.dataset import HoldingContext, build_fund_dataset, build_stock_dataset
from app.modules.analysis.provider import CompatibleAIClient
from app.modules.analysis.schemas import AnalysisConclusion
from app.modules.market_data.models import FundDailyNav, StockDailyBar

pytestmark = pytest.mark.anyio

_MODEL_RESULT = {
    "conclusion": "NEUTRAL",
    "summary": "当前趋势和风险指标相互制约，暂时没有足够证据支持单边结论。",
    "highlights": ["阶段走势保持稳定"],
    "risks": ["历史表现不能代表未来收益"],
    "actions": ["继续关注后续数据变化"],
}


@pytest.fixture
def anyio_backend() -> str:
    """模型协议异步测试统一使用 asyncio。"""
    return "asyncio"


async def test_openai_compatible_client_parses_structured_result() -> None:
    """OpenAI 兼容协议应使用 Bearer 鉴权并解析消息文本。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://llm.example/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": _json_text(_MODEL_RESULT)}}]},
        )

    client = CompatibleAIClient(
        provider="openai",
        base_url="https://llm.example/v1",
        api_key="test-key",
        model="test-model",
        timeout_seconds=30,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await client.generate(system_prompt="system", user_prompt="user")
    assert result.conclusion is AnalysisConclusion.NEUTRAL


async def test_gpt_5_6_client_uses_reasoning_compatible_parameters() -> None:
    """GPT-5.6 应使用新版输出上限、developer 消息和低推理强度。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["messages"][0]["role"] == "developer"
        assert payload["reasoning_effort"] == "low"
        assert payload["max_completion_tokens"] == 3000
        assert payload["response_format"] == {"type": "json_object"}
        assert "max_tokens" not in payload
        assert "temperature" not in payload
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": _json_text(_MODEL_RESULT)}}]},
        )

    client = CompatibleAIClient(
        provider="openai",
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        model="gpt-5.6-sol",
        timeout_seconds=30,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await client.generate(system_prompt="system", user_prompt="user")
    assert result.conclusion is AnalysisConclusion.NEUTRAL


async def test_anthropic_compatible_client_parses_text_blocks() -> None:
    """Claude 兼容协议应发送版本头并合并文本内容块。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://claude.example/v1/messages"
        assert request.headers["x-api-key"] == "test-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": _json_text(_MODEL_RESULT)}]},
        )

    client = CompatibleAIClient(
        provider="anthropic",
        base_url="https://claude.example/v1",
        api_key="test-key",
        model="test-model",
        timeout_seconds=30,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await client.generate(system_prompt="system", user_prompt="user")
    assert result.summary == _MODEL_RESULT["summary"]


def test_stock_dataset_contains_holding_metrics() -> None:
    """股票数据集应使用最新收盘价计算用户持仓指标。"""
    start = date(2026, 1, 1)
    bars = [
        StockDailyBar(
            instrument_id=None,
            trade_date=start + timedelta(days=index),
            open=Decimal(100 + index),
            high=Decimal(102 + index),
            low=Decimal(99 + index),
            close=Decimal(101 + index),
            previous_close=Decimal(100 + index),
            volume=Decimal(1000 + index),
            turnover=None,
            source="test_stock",
        )
        for index in range(61)
    ]
    dataset = build_stock_dataset(
        bars,
        holding=HoldingContext(quantity=Decimal("10"), total_cost=Decimal("1200")),
    )
    metrics = {item.label: item.value for item in dataset.metrics}
    assert metrics["最新收盘"] == "161.00"
    assert metrics["我的持仓金额"] == "1,610.00"
    assert dataset.facts["rsi14"] == 100.0


def test_fund_dataset_uses_official_nav_history() -> None:
    """基金数据集只应使用官方净值计算阶段收益和回撤。"""
    start = date(2026, 1, 1)
    navs = [
        FundDailyNav(
            instrument_id=None,
            nav_date=start + timedelta(days=index),
            unit_nav=Decimal("1") + Decimal(index) / Decimal("1000"),
            accumulated_nav=None,
            daily_return_rate=None,
            fetched_at=datetime(2026, 8, 27, tzinfo=UTC),
            first_observed_at=datetime(2026, 8, 27, tzinfo=UTC),
            source="test_fund_official",
        )
        for index in range(61)
    ]
    dataset = build_fund_dataset(navs, holding=None)
    metrics = {item.label: item.value for item in dataset.metrics}
    assert metrics["最新净值"] == "1.0600"
    assert dataset.data_sources == ("test_fund_official",)
    assert dataset.facts["return60d"] == pytest.approx(0.06)


def _json_text(value: object) -> str:
    """生成模型兼容测试需要的紧凑 JSON 文本。"""
    return json.dumps(value, ensure_ascii=False)
