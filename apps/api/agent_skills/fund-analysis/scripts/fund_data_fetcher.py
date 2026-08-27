"""获取基金官方历史净值并计算可复核的基础风险指标。"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_HISTORY_URL = "https://api.fund.eastmoney.com/f10/lsjz"
_HEADERS = {
    "User-Agent": "ai-pick-stock-agent/1.0",
    "Referer": "https://fundf10.eastmoney.com/",
}


def fetch_history(ticker: str, *, limit: int = 500) -> list[dict[str, Any]]:
    """读取并按净值日期升序返回官方历史净值。"""
    rows: list[dict[str, Any]] = []
    page_size = min(limit, 20)
    page_count = math.ceil(limit / page_size)
    for page_index in range(1, page_count + 1):
        page_rows = _fetch_history_page(ticker, page_index, page_size)
        rows.extend(page_rows)
        if len(page_rows) < page_size:
            break
    rows = rows[:limit]
    history = [
        {
            "date": row["FSRQ"],
            "unitNav": float(row["DWJZ"]),
            "accumulatedNav": _optional_float(row.get("LJJZ")),
            "dailyChangeRate": _optional_percent(row.get("JZZZL")),
        }
        for row in rows
        if row.get("FSRQ") and row.get("DWJZ")
    ]
    if len(history) < 2:
        raise ValueError("基金历史净值不足两个净值日")
    return sorted(history, key=lambda item: item["date"])


def _fetch_history_page(
    ticker: str,
    page_index: int,
    page_size: int,
) -> list[dict[str, Any]]:
    """读取单页基金官方历史净值，并严格校验上游响应结构。"""
    query = urlencode(
        {
            "fundCode": ticker,
            "pageIndex": str(page_index),
            "pageSize": str(page_size),
        }
    )
    headers = {**_HEADERS, "Referer": f"https://fundf10.eastmoney.com/jjjz_{ticker}.html"}
    request = Request(f"{_HISTORY_URL}?{query}", headers=headers)
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("基金历史净值响应异常")
    if payload.get("ErrCode") != 0:
        raise ValueError("基金历史净值接口返回失败状态")
    data = payload.get("Data")
    rows = data.get("LSJZList") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("基金历史净值结构异常")
    return [row for row in rows if isinstance(row, dict)]


def build_report(ticker: str, history: list[dict[str, Any]]) -> dict[str, Any]:
    """把净值序列转换为阶段收益、趋势、波动和回撤指标。"""
    values = [float(item["unitNav"]) for item in history]
    latest = history[-1]
    maximum_drawdown, current_drawdown = _drawdowns(values)
    return {
        "fund": ticker,
        "latestOfficialNav": latest,
        "historyCount": len(history),
        "periodReturns": {
            "5NavDays": _period_return(values, 5),
            "20NavDays": _period_return(values, 20),
            "60NavDays": _period_return(values, 60),
            "120NavDays": _period_return(values, 120),
            "250NavDays": _period_return(values, 250),
        },
        "movingAverages": {
            "ma5": _moving_average(values, 5),
            "ma20": _moving_average(values, 20),
            "ma60": _moving_average(values, 60),
        },
        "maximumDrawdown": maximum_drawdown,
        "currentDrawdown": current_drawdown,
        "annualizedVolatility": _annualized_volatility(values),
        "recentOfficialNavs": history[-30:],
        "dataSource": "eastmoney_fund_official_history",
        "fetchedAt": datetime.now(UTC).isoformat(),
    }


def _period_return(values: list[float], days: int) -> float | None:
    """计算相隔指定净值日的简单收益率。"""
    if len(values) <= days or values[-days - 1] <= 0:
        return None
    return values[-1] / values[-days - 1] - 1


def _moving_average(values: list[float], days: int) -> float | None:
    """计算最近指定净值日的算术平均净值。"""
    if len(values) < days:
        return None
    return sum(values[-days:]) / days


def _drawdowns(values: list[float]) -> tuple[float, float]:
    """计算全序列最大回撤和当前回撤。"""
    peak = values[0]
    maximum = 0.0
    current = 0.0
    for value in values:
        peak = max(peak, value)
        current = value / peak - 1
        maximum = min(maximum, current)
    return maximum, current


def _annualized_volatility(values: list[float]) -> float | None:
    """按最近最多 250 个净值日收益计算年化波动。"""
    returns = [
        current / previous - 1
        for previous, current in zip(values, values[1:], strict=False)
        if previous > 0
    ][-250:]
    if len(returns) < 2:
        return None
    return statistics.stdev(returns) * math.sqrt(250)


def _optional_float(value: object) -> float | None:
    """把可空文本转换为浮点数。"""
    return None if value in {None, ""} else float(str(value))


def _optional_percent(value: object) -> float | None:
    """把可空百分数字段转换为比值。"""
    return None if value in {None, ""} else float(str(value)) / 100


def main() -> int:
    """解析命令行参数并输出单个 JSON 对象。"""
    parser = argparse.ArgumentParser(description="获取基金官方净值分析数据")
    parser.add_argument("--fund", required=True, help="六位基金代码")
    args = parser.parse_args()
    ticker = args.fund.strip()
    if len(ticker) != 6 or not ticker.isdigit():
        print("基金代码必须是六位数字", file=sys.stderr)
        return 2
    try:
        print(json.dumps(build_report(ticker, fetch_history(ticker)), ensure_ascii=False))
    except Exception as error:
        print(f"基金数据获取失败：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
