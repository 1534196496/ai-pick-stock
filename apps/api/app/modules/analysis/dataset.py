"""从真实行情和用户持仓构造可审计的 AI 分析数据集。"""

from dataclasses import dataclass
from decimal import Decimal
from math import sqrt
from statistics import stdev
from typing import Any

from app.modules.instruments.domain import InstrumentRecord
from app.modules.market_data.models import FundDailyNav, StockDailyBar


@dataclass(frozen=True, slots=True)
class HoldingContext:
    """表示当前用户在全部分组中的聚合持仓。"""

    quantity: Decimal
    total_cost: Decimal


@dataclass(frozen=True, slots=True)
class AnalysisMetric:
    """保存一项面向用户展示的指标。"""

    label: str
    value: str


@dataclass(frozen=True, slots=True)
class AnalysisDataset:
    """保存传给模型的事实、最近序列及页面展示指标。"""

    data_as_of: str
    data_sources: tuple[str, ...]
    metrics: tuple[AnalysisMetric, ...]
    facts: dict[str, Any]
    recent_series: tuple[dict[str, str], ...]

    def prompt_context(self, instrument: InstrumentRecord) -> dict[str, Any]:
        """生成不包含密钥和内部 ID 的模型输入对象。"""
        return {
            "instrument": {
                "assetType": instrument.asset_type.value,
                "market": instrument.market.value,
                "ticker": instrument.ticker,
                "name": instrument.name,
                "currency": instrument.currency.value,
            },
            "dataAsOf": self.data_as_of,
            "dataSources": list(self.data_sources),
            "facts": self.facts,
            "recentSeries": list(self.recent_series),
        }


def build_stock_dataset(
    bars: list[StockDailyBar],
    *,
    holding: HoldingContext | None,
) -> AnalysisDataset:
    """计算股票趋势、波动、回撤、量能和持仓相关事实。"""
    closes = [float(item.close) for item in bars]
    volumes = [float(item.volume) for item in bars if item.volume is not None]
    latest = bars[-1]
    latest_price = latest.close
    return_20 = _period_return(closes, 20)
    return_60 = _period_return(closes, 60)
    volatility = _annualized_volatility(closes)
    max_drawdown, current_drawdown = _drawdowns(closes)
    ma20 = _moving_average(closes, 20)
    ma60 = _moving_average(closes, 60)
    rsi14 = _rsi(closes, 14)
    volume_ratio = _volume_ratio(volumes)
    metrics = [
        AnalysisMetric("最新收盘", _price(latest_price, 2)),
        AnalysisMetric("近20日", _percent(return_20)),
        AnalysisMetric("近60日", _percent(return_60)),
        AnalysisMetric("最大回撤", _percent(max_drawdown)),
        AnalysisMetric("年化波动", _percent(volatility)),
        AnalysisMetric("RSI14", _number(rsi14, 1)),
    ]
    holding_facts, holding_metrics = _holding_facts(holding, latest_price)
    metrics.extend(holding_metrics)
    facts: dict[str, Any] = {
        "historyCount": len(bars),
        "latestClose": _plain(latest_price),
        "return20d": return_20,
        "return60d": return_60,
        "ma20": ma20,
        "ma60": ma60,
        "rsi14": rsi14,
        "annualizedVolatility": volatility,
        "maxDrawdown": max_drawdown,
        "currentDrawdown": current_drawdown,
        "volumeRatio5d": volume_ratio,
        "support20d": min(closes[-20:]),
        "resistance20d": max(closes[-20:]),
        "holding": holding_facts,
    }
    series = tuple(
        {
            "date": item.trade_date.isoformat(),
            "close": _plain(item.close),
            "volume": _plain(item.volume) if item.volume is not None else "",
        }
        for item in bars[-30:]
    )
    return AnalysisDataset(
        data_as_of=latest.trade_date.isoformat(),
        data_sources=tuple(dict.fromkeys(item.source for item in bars)),
        metrics=tuple(metrics),
        facts=facts,
        recent_series=series,
    )


def build_fund_dataset(
    navs: list[FundDailyNav],
    *,
    holding: HoldingContext | None,
) -> AnalysisDataset:
    """计算基金阶段收益、波动、回撤、净值趋势和持仓事实。"""
    values = [float(item.unit_nav) for item in navs]
    latest = navs[-1]
    latest_nav = latest.unit_nav
    return_20 = _period_return(values, 20)
    return_60 = _period_return(values, 60)
    return_250 = _period_return(values, 250)
    volatility = _annualized_volatility(values)
    max_drawdown, current_drawdown = _drawdowns(values)
    ma20 = _moving_average(values, 20)
    ma60 = _moving_average(values, 60)
    metrics = [
        AnalysisMetric("最新净值", _price(latest_nav, 4)),
        AnalysisMetric("近20日", _percent(return_20)),
        AnalysisMetric("近60日", _percent(return_60)),
        AnalysisMetric("近一年", _percent(return_250)),
        AnalysisMetric("最大回撤", _percent(max_drawdown)),
        AnalysisMetric("年化波动", _percent(volatility)),
    ]
    holding_facts, holding_metrics = _holding_facts(holding, latest_nav)
    metrics.extend(holding_metrics)
    facts: dict[str, Any] = {
        "historyCount": len(navs),
        "latestOfficialNav": _plain(latest_nav),
        "return20d": return_20,
        "return60d": return_60,
        "return250d": return_250,
        "ma20": ma20,
        "ma60": ma60,
        "annualizedVolatility": volatility,
        "maxDrawdown": max_drawdown,
        "currentDrawdown": current_drawdown,
        "holding": holding_facts,
    }
    series = tuple(
        {
            "date": item.nav_date.isoformat(),
            "unitNav": _plain(item.unit_nav),
        }
        for item in navs[-30:]
    )
    return AnalysisDataset(
        data_as_of=latest.nav_date.isoformat(),
        data_sources=tuple(dict.fromkeys(item.source for item in navs)),
        metrics=tuple(metrics),
        facts=facts,
        recent_series=series,
    )


def _holding_facts(
    holding: HoldingContext | None,
    latest_price: Decimal,
) -> tuple[dict[str, str] | None, list[AnalysisMetric]]:
    """按最新权威价格计算用户聚合持仓金额和收益率。"""
    if holding is None or holding.quantity <= 0:
        return None, []
    market_value = holding.quantity * latest_price
    profit = market_value - holding.total_cost
    return_rate = profit / holding.total_cost if holding.total_cost > 0 else None
    facts = {
        "quantity": _plain(holding.quantity),
        "totalCost": _plain(holding.total_cost),
        "marketValue": _plain(market_value),
        "holdingProfit": _plain(profit),
        "holdingReturnRate": str(return_rate) if return_rate is not None else "",
    }
    metrics = [
        AnalysisMetric("我的持仓金额", f"{market_value:,.2f}"),
        AnalysisMetric(
            "我的持仓收益率", _percent(float(return_rate) if return_rate is not None else None)
        ),
    ]
    return facts, metrics


def _period_return(values: list[float], days: int) -> float | None:
    """计算相隔指定交易日的简单收益率。"""
    if len(values) <= days or values[-days - 1] <= 0:
        return None
    return values[-1] / values[-days - 1] - 1


def _moving_average(values: list[float], days: int) -> float | None:
    """计算最近指定交易日的算术移动平均。"""
    if len(values) < days:
        return None
    return sum(values[-days:]) / days


def _annualized_volatility(values: list[float]) -> float | None:
    """使用最近最多 250 个交易日收益率计算年化波动率。"""
    returns = [
        current / previous - 1
        for previous, current in zip(values, values[1:], strict=False)
        if previous > 0
    ]
    recent = returns[-250:]
    if len(recent) < 2:
        return None
    return stdev(recent) * sqrt(250)


def _drawdowns(values: list[float]) -> tuple[float | None, float | None]:
    """计算历史最大回撤与当前距离历史高点的回撤。"""
    if not values:
        return None, None
    peak = values[0]
    maximum = 0.0
    current = 0.0
    for value in values:
        peak = max(peak, value)
        current = value / peak - 1 if peak > 0 else 0.0
        maximum = min(maximum, current)
    return maximum, current


def _rsi(values: list[float], period: int) -> float | None:
    """使用最近指定周期涨跌幅计算简化 RSI。"""
    if len(values) <= period:
        return None
    changes = [
        current - previous for previous, current in zip(values, values[1:], strict=False)
    ][-period:]
    gains = sum(max(change, 0) for change in changes) / period
    losses = sum(max(-change, 0) for change in changes) / period
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    strength = gains / losses
    return 100 - 100 / (1 + strength)


def _volume_ratio(volumes: list[float]) -> float | None:
    """计算最新成交量相对此前五日平均量的倍数。"""
    if len(volumes) < 6:
        return None
    average = sum(volumes[-6:-1]) / 5
    return volumes[-1] / average if average > 0 else None


def _percent(value: float | None) -> str:
    """把比值格式化为带符号百分数，缺失时显示横线。"""
    return "—" if value is None else f"{value:+.2%}"


def _number(value: float | None, digits: int) -> str:
    """格式化普通数值，缺失时显示横线。"""
    return "—" if value is None else f"{value:.{digits}f}"


def _price(value: Decimal, digits: int) -> str:
    """按股票或基金展示精度格式化价格。"""
    return f"{value:.{digits}f}"


def _plain(value: Decimal | None) -> str:
    """把 Decimal 转为不使用科学计数法的字符串。"""
    return "" if value is None else format(value, "f")
