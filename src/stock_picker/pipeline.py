from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
import uuid

import pandas as pd

from .config import Settings
from .db import Database
from .provider import AkshareProvider
from .scoring import calculate_features, score_stocks


def select_universe(spot: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    frame = spot.copy()
    excluded = frame["name"].apply(lambda name: any(key.upper() in name.upper() for key in settings.exclude_name_keywords))
    valid_codes = frame["code"].str.match(r"^(00|30|60|68)\d{4}$")
    frame = frame[~excluded & valid_codes & (frame["amount"] >= settings.min_daily_amount_cny)]
    return frame.sort_values("amount", ascending=False).head(settings.universe_size).reset_index(drop=True)


def sync_data(settings: Settings, workers: int = 6) -> dict:
    if settings.provider != "akshare":
        raise ValueError(f"尚不支持 provider={settings.provider}")
    db = Database(settings.database)
    provider = AkshareProvider()
    now = datetime.now()
    spot = provider.spot()
    spot_source = provider.last_source
    universe = select_universe(spot, settings)
    if universe.empty:
        raise RuntimeError("筛选后股票池为空，请检查行情或放宽 config.toml 条件")
    db.upsert_instruments(universe[["code", "name"]], now.isoformat(timespec="seconds"))
    db.upsert_snapshots(universe, date.today().isoformat(), spot_source)
    last_dates = db.query_df("SELECT code, MAX(trade_date) AS last_date FROM daily_prices GROUP BY code")
    last_by_code = dict(zip(last_dates.get("code", []), last_dates.get("last_date", [])))
    end = date.today()
    default_start = end - timedelta(days=settings.history_calendar_days)
    failures: list[str] = []
    frames: list[pd.DataFrame] = []
    sources: dict[str, str] = {}

    def fetch(code: str):
        history_provider = AkshareProvider()
        last = last_by_code.get(code)
        start = max(default_start, date.fromisoformat(last) + timedelta(days=1)) if last else default_start
        if start > end:
            return pd.DataFrame()
        frame = history_provider.history(code, start, end, settings.adjust)
        return frame, history_provider.last_source

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(fetch, code): code for code in universe["code"]}
        for future in as_completed(futures):
            code = futures[future]
            try:
                frame, source = future.result()
                if not frame.empty:
                    frames.append(frame)
                    sources[code] = source
            except Exception as error:
                failures.append(f"{code}: {error}")
    for frame in frames:
        code = str(frame.iloc[0]["code"])
        db.upsert_prices(frame, sources.get(code, "unknown"), settings.adjust)
    return {"universe": len(universe), "updated": len(frames), "failures": failures, "source": spot_source}


def run_selection(settings: Settings) -> tuple[pd.DataFrame, Path]:
    db = Database(settings.database)
    latest_snapshot = db.query_df("SELECT MAX(snapshot_date) AS value FROM snapshots").iloc[0]["value"]
    if not latest_snapshot:
        raise RuntimeError("本地没有行情快照，请先运行 sync")
    snapshots = db.query_df("SELECT * FROM snapshots WHERE snapshot_date=?", (latest_snapshot,))
    current_codes = tuple(snapshots["code"].tolist())
    placeholders = ",".join("?" for _ in current_codes)
    prices = db.query_df(f"SELECT * FROM daily_prices WHERE code IN ({placeholders})", current_codes)
    instruments = db.query_df("SELECT code, name FROM instruments")
    if prices.empty:
        raise RuntimeError("本地没有价格数据，请先运行 sync")
    latest_by_code = prices.groupby("code")["trade_date"].max()
    common_as_of = latest_by_code.max()
    fresh_codes = latest_by_code[latest_by_code == common_as_of].index
    if len(fresh_codes) != len(current_codes):
        raise RuntimeError(f"行情不完整：仅 {len(fresh_codes)}/{len(current_codes)} 只股票达到共同最新交易日，拒绝生成正式候选")
    prices = prices[prices["code"].isin(fresh_codes)]
    snapshots = snapshots[snapshots["code"].isin(fresh_codes)]
    features = calculate_features(prices, snapshots, settings.min_listing_days)
    ranked = score_stocks(features, settings.weights, settings.max_pe, settings.max_pb)
    ranked = ranked.merge(instruments, on="code", how="left")
    picks = ranked.head(settings.top_n).copy()
    picks.insert(0, "rank", range(1, len(picks) + 1))
    run_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    as_of = str(prices["trade_date"].max())
    created_at = datetime.now().isoformat(timespec="seconds")
    expected = len(current_codes)
    lag_days = (date.today() - date.fromisoformat(str(common_as_of))).days
    if lag_days > 7:
        raise RuntimeError(f"共同数据日 {common_as_of} 距今天 {lag_days} 天，数据陈旧，拒绝生成正式候选")
    status = "success"
    message = None
    with db.connect() as con:
        con.execute("UPDATE runs SET status='superseded' WHERE status='success'")
        con.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?)", (run_id, as_of, created_at, expected, len(ranked), status, message))
        rows = []
        for row in picks.itertuples():
            rows.append((run_id, row.rank, row.code, row.name, row.score, row.close, row.pe, row.pb, row.return_20d, row.return_60d, row.return_120d, row.volatility_20d, row.max_drawdown_120d, row.avg_amount_20d, row.reasons))
        con.executemany("INSERT INTO picks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    report = write_report(settings.reports, run_id, as_of, picks, len(ranked))
    return picks, report


def write_report(folder: Path, run_id: str, as_of: str, picks: pd.DataFrame, scored_count: int) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    report_path = folder / f"{as_of}-selection.md"
    csv_path = folder / f"{as_of}-selection.csv"
    picks.to_csv(csv_path, index=False, encoding="utf-8-sig")
    lines = [
        f"# A股候选清单 — {as_of}", "",
        f"> 运行编号：`{run_id}`；有效样本：{scored_count}。本报告仅用于研究，不构成投资建议。", "",
        "| 排名 | 代码 | 名称 | 评分 | 收盘 | 20日 | 60日 | 年化波动 | 120日最大回撤 | PE | PB | 入选理由 |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in picks.itertuples():
        fmt = lambda value, suffix="": "—" if pd.isna(value) else f"{value:.2f}{suffix}"
        lines.append(
            f"| {row.rank} | {row.code} | {row.name} | {row.score:.1f} | {row.close:.2f} | {fmt(row.return_20d*100, '%')} | {fmt(row.return_60d*100, '%')} | {fmt(row.volatility_20d*100, '%')} | {fmt(row.max_drawdown_120d*100, '%')} | {fmt(row.pe)} | {fmt(row.pb)} | {row.reasons} |"
        )
    lines += ["", "## 口径与风险", "", "- 评分是同一候选池内的相对排名，不是收益率预测。", "- 前复权历史用于趋势计算；估值取当日行情快照，数据源异常时可能缺失。", "- 低流动性、ST/退市风险标的已过滤，但无法覆盖财务造假、突发公告、行业周期等风险。", "- 下单前应复核最新公告、财报、仓位与自身风险承受能力。", ""]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
