"""显式联网验证免费行情候选源，只输出脱敏结构摘要。"""

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "ai-pick-stock-source-smoke/2.0 (+public-read-only-validation)"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """保存不含完整第三方响应的可行性证据。"""

    source: str
    status: str
    latency_ms: int
    response_bytes: int
    coverage_count: int | None
    sample_fields: list[str]
    note: str


def fetch(url: str, *, referer: str, timeout: float = 12) -> tuple[bytes, int]:
    """执行带超时的只读 GET，并返回响应体和毫秒延迟。"""
    request = Request(
        url,
        headers={"User-Agent": USER_AGENT, "Referer": referer, "Accept": "*/*"},
    )
    started = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
    return body, round((time.perf_counter() - started) * 1000)


def probe_tencent_stock_master() -> ProbeResult:
    """验证腾讯 A 股榜单的主数据覆盖和字段。"""
    url = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList?" + urlencode(
        {
            "_appver": "11.17.0",
            "board_code": "aStock",
            "sort_type": "price",
            "direct": "down",
            "offset": "0",
            "count": "5",
        }
    )
    body, latency = fetch(url, referer="https://stockapp.finance.qq.com/")
    payload = json.loads(body)
    rows = payload["data"]["rank_list"]
    return ProbeResult(
        source="tencent_stock_rank",
        status="ok",
        latency_ms=latency,
        response_bytes=len(body),
        coverage_count=int(payload["data"]["total"]),
        sample_fields=sorted(rows[0].keys()),
        note="榜单同时提供代码、名称和最新价；无公开 SLA，需边界校验",
    )


def probe_sina_stock_fallback() -> ProbeResult:
    """验证新浪批量股票行情回退端点。"""
    body, latency = fetch(
        "https://hq.sinajs.cn/list=sh600519,sz000001",
        referer="https://finance.sina.com.cn/",
    )
    text = body.decode("gb18030")
    rows = [line for line in text.splitlines() if '="' in line]
    if len(rows) != 2:
        raise ValueError("新浪样本行数异常")
    return ProbeResult(
        source="sina_stock_quote",
        status="ok",
        latency_ms=latency,
        response_bytes=len(body),
        coverage_count=len(rows),
        sample_fields=["name", "open", "previousClose", "last", "date", "time"],
        note="GB18030 文本；仅作为已知代码行情回退，不承担主数据发现",
    )


def probe_eastmoney_fund_master() -> ProbeResult:
    """验证天天基金主数据脚本的覆盖和固定五列结构。"""
    body, latency = fetch(
        "https://fund.eastmoney.com/js/fundcode_search.js",
        referer="https://fund.eastmoney.com/",
    )
    text = body.decode("utf-8-sig").strip()
    rows = json.loads(text.removeprefix("var r = ").removesuffix(";"))
    if not rows or any(len(row) != 5 for row in rows[:20]):
        raise ValueError("基金主数据结构异常")
    return ProbeResult(
        source="eastmoney_fund_master",
        status="ok",
        latency_ms=latency,
        response_bytes=len(body),
        coverage_count=len(rows),
        sample_fields=["ticker", "pinyinAbbr", "name", "fundType", "pinyin"],
        note="大响应每日低频同步；基金类型需映射，不能把累计净值当单位净值",
    )


def probe_eastmoney_official_nav() -> ProbeResult:
    """验证天天基金开放式基金官方净值批量页面。"""
    url = "https://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx?" + urlencode(
        {
            "t": "1",
            "lx": "1",
            "letter": "",
            "gsid": "",
            "text": "",
            "sort": "zdf,desc",
            "page": "1,5",
            "dt": str(int(time.time() * 1000)),
            "atfc": "",
            "onlySale": "0",
        }
    )
    body, latency = fetch(url, referer="https://fund.eastmoney.com/")
    text = body.decode("utf-8-sig")
    record = re.search(r'record:"(\d+)"', text)
    showday = re.search(r"showday:(\[[^]]+\])", text)
    data_rows = re.search(r"datas:(\[.*?\]),count:", text)
    if record is None or showday is None or data_rows is None:
        raise ValueError("官方净值页面结构异常")
    rows = json.loads(data_rows.group(1))
    dates = json.loads(showday.group(1))
    return ProbeResult(
        source="eastmoney_fund_official_bulk",
        status="ok",
        latency_ms=latency,
        response_bytes=len(body),
        coverage_count=int(record.group(1)),
        sample_fields=["ticker", "name", "unitNav", "accumulatedNav", "previousUnitNav"],
        note=(f"页面公布业务日期 {dates}; 样本 {len(rows)} 行; 批量端点为晚间官方净值首选"),
    )


def probe_eastmoney_official_fallback() -> ProbeResult:
    """验证单基金页面脚本可作为官方净值低频回退。"""
    body, latency = fetch(
        f"https://fund.eastmoney.com/pingzhongdata/000001.js?v={int(time.time())}",
        referer="https://fund.eastmoney.com/000001.html",
    )
    text = body.decode("utf-8-sig")
    match = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", text)
    if match is None:
        raise ValueError("单基金净值走势结构异常")
    rows = json.loads(match.group(1))
    last = rows[-1]
    return ProbeResult(
        source="eastmoney_fund_official_single",
        status="ok",
        latency_ms=latency,
        response_bytes=len(body),
        coverage_count=len(rows),
        sample_fields=sorted(last.keys()),
        note="单基金响应较大且较慢，仅在批量源失败时对活跃基金限量回退",
    )


def probe_estimate_candidate() -> ProbeResult:
    """验证估算净值候选；失败也作为禁用默认源的证据。"""
    url = "https://api.fund.eastmoney.com/FundGuZhi/GetFundGZList?" + urlencode(
        {"type": "1", "pageIndex": "1", "pageSize": "5"}
    )
    try:
        body, latency = fetch(url, referer="https://fund.eastmoney.com/", timeout=8)
        payload = json.loads(body)
        rows = (payload.get("Data") or {}).get("list") or []
        return ProbeResult(
            source="eastmoney_fund_estimate_candidate",
            status="ok" if rows else "empty",
            latency_ms=latency,
            response_bytes=len(body),
            coverage_count=len(rows),
            sample_fields=sorted(rows[0].keys()) if rows and isinstance(rows[0], dict) else [],
            note="估算值非官方净值；仅可选展示，不能进入权威组合汇总",
        )
    except (OSError, URLError, TimeoutError, ValueError, RuntimeError) as error:
        return ProbeResult(
            source="eastmoney_fund_estimate_candidate",
            status="unreachable",
            latency_ms=8000,
            response_bytes=0,
            coverage_count=None,
            sample_fields=[],
            note=f"当前服务器不可达：{type(error).__name__}; 默认禁用并保留旧值",
        )


def main() -> None:
    """仅在显式 --live 时执行联网探测并输出 JSON 摘要。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        raise SystemExit("必须显式传入 --live 才会访问外部数据源")
    probes = [
        probe_tencent_stock_master,
        probe_sina_stock_fallback,
        probe_eastmoney_fund_master,
        probe_eastmoney_official_nav,
        probe_eastmoney_official_fallback,
        probe_estimate_candidate,
    ]
    results: list[dict[str, Any]] = []
    for probe in probes:
        try:
            results.append(asdict(probe()))
        except (OSError, URLError, TimeoutError, ValueError, RuntimeError) as error:
            results.append(
                asdict(
                    ProbeResult(
                        source=probe.__name__,
                        status="failed",
                        latency_ms=0,
                        response_bytes=0,
                        coverage_count=None,
                        sample_fields=[],
                        note=f"{type(error).__name__}; 未记录响应正文",
                    )
                )
            )
    print(json.dumps({"testedAt": "2026-08-24", "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
