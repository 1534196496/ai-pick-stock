"""Provider 固定样本和异常边界测试。"""

import json
from datetime import UTC
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.market_data.providers.schemas import (
    FundEstimatedNavSnapshot,
    FundOfficialNavSnapshot,
    ProviderInstrument,
    StockPriceSnapshot,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "providers"


def load_fixture(name: str) -> dict[str, object]:
    """读取版本化且完全虚构的 Provider 样本。"""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_stock_price_fixture_preserves_decimal_and_utc_time() -> None:
    """股票价格字符串转换为 Decimal，业务时间保留 UTC。"""
    snapshot = StockPriceSnapshot.model_validate(load_fixture("stock_price.json"))
    assert snapshot.value == Decimal("1421.35")
    assert snapshot.as_of_at.utcoffset() == UTC.utcoffset(snapshot.as_of_at)


def test_fund_official_and_estimated_nav_are_different_types() -> None:
    """官方单位净值、累计净值和估算净值不能共用一个模糊模型。"""
    official = FundOfficialNavSnapshot.model_validate(load_fixture("fund_official_nav.json"))
    estimated = FundEstimatedNavSnapshot.model_validate(load_fixture("fund_estimated_nav.json"))
    assert official.unit_nav == Decimal("1.2345")
    assert official.accumulated_nav == Decimal("4.5678")
    assert estimated.estimated_nav == Decimal("1.2410")
    assert not hasattr(estimated, "unit_nav")


@pytest.mark.parametrize(
    "payload",
    [
        {
            "ticker": "600519",
            "value": 1.2,
            "as_of_at": "2026-08-24T07:00:00Z",
            "fetched_at": "2026-08-24T07:00:03Z",
            "source": "bad-float",
        },
        {
            "ticker": "600519",
            "value": "0",
            "as_of_at": "2026-08-24T07:00:00Z",
            "fetched_at": "2026-08-24T07:00:03Z",
            "source": "bad-zero",
        },
        {
            "ticker": "600519",
            "value": "1",
            "fetched_at": "2026-08-24T07:00:03Z",
            "source": "missing-time",
        },
        {**load_fixture("stock_price.json"), "unexpected": "field"},
    ],
)
def test_stock_boundary_rejects_float_zero_missing_and_unknown_fields(
    payload: dict[str, object],
) -> None:
    """字段漂移或不安全财务类型必须在适配器边界失败。"""
    with pytest.raises(ValidationError):
        StockPriceSnapshot.model_validate(payload)


def test_instrument_schema_rejects_stock_with_fund_exchange() -> None:
    """资产类型与交易所组合不一致时拒绝。"""
    with pytest.raises(ValidationError):
        ProviderInstrument.model_validate(
            {
                "asset_type": "STOCK",
                "market": "CN",
                "exchange": "FUND_CN",
                "ticker": "600000",
                "name": "虚构股票",
                "currency": "CNY",
                "source": "fixture",
                "source_updated_at": None,
            }
        )
