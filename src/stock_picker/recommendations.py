from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import uuid

import numpy as np
import pandas as pd

from .analysis import cached_fund_history
from .db import Database
from .provider import AkshareProvider


STOCK_MODEL_VERSION = "a-share-quality-v3-small-sample-calibrated"
FUND_MODEL_VERSION = "cn-fund-quality-risk-v4"
STOCK_CLASSIFICATION_VERSION = "cn-source-industry-v2"
FUND_CATEGORIES = ("股票型", "混合型", "债券型", "指数型", "FOF", "QDII")
STOCK_SOURCE = "AKShare / 东方财富与腾讯公开行情"
FUND_SOURCE = "AKShare / 东方财富基金排行"


def _now() -> str:
    return pd.Timestamp.now(tz="Asia/Shanghai").isoformat()


def _identifier(prefix: str) -> str:
    return f"{prefix}-{datetime.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


def _latest_a_share_session(today: date | None = None) -> str:
    today = today or date.today()
    try:
        import exchange_calendars as xcals

        session = xcals.get_calendar("XSHG").date_to_session(pd.Timestamp(today), direction="previous")
        return session.strftime("%Y-%m-%d")
    except Exception:
        return pd.bdate_range(end=pd.Timestamp(today), periods=1)[0].strftime("%Y-%m-%d")


def _rank(series: pd.Series, higher: bool = True) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    return clean.rank(pct=True, ascending=higher).fillna(0.0)


def _shrunk_rank(series: pd.Series, higher: bool = True, prior_strength: int = 4) -> pd.Series:
    """Shrink thin-section percentiles toward neutral instead of awarding singleton 100s."""
    ranked = _rank(series, higher)
    observed = int(pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).notna().sum())
    weight = observed / (observed + max(1, prior_strength))
    return 0.5 + (ranked - 0.5) * weight


def _board(code: str) -> tuple[str, str]:
    code = str(code).zfill(6)
    if code.startswith("68"):
        return "上海证券交易所", "科创板"
    if code.startswith("60"):
        return "上海证券交易所", "沪市主板"
    if code.startswith("30"):
        return "深圳证券交易所", "创业板"
    if code.startswith("00"):
        return "深圳证券交易所", "深市主板"
    if code.startswith(("4", "8", "92")):
        return "北京证券交易所", "北交所"
    return "中国A股", "其他"


SECTOR_RULES = (
    ("信息技术", ("软件", "计算机", "电子", "半导体", "元件", "通信", "互联网", "IT")),
    ("医疗保健", ("医药", "医疗", "生物", "制药", "健康")),
    ("金融", ("银行", "保险", "证券", "多元金融", "信托")),
    ("可选消费", ("汽车", "家居", "旅游", "酒店", "传媒", "教育", "纺织", "服装", "零售", "娱乐")),
    ("日常消费", ("食品", "饮料", "农业", "养殖", "农牧", "酒类")),
    ("工业", ("机械", "设备", "运输", "物流", "航空", "军工", "建筑", "工程", "电气")),
    ("能源", ("煤炭", "石油", "油气", "能源")),
    ("材料", ("化工", "有色", "钢铁", "建材", "材料", "矿业", "造纸")),
    ("公用事业", ("电力", "水务", "燃气", "环保", "公用")),
    ("房地产", ("房地产", "物业", "园区开发")),
)


def normalize_stock_sector(raw_sector: object) -> str:
    value = "" if pd.isna(raw_sector) else str(raw_sector).strip()
    if not value:
        return "行业待分类"
    for section, keywords in SECTOR_RULES:
        if any(keyword.lower() in value.lower() for keyword in keywords):
            return section
    # Keep the source industry instead of mixing unrelated unmatched companies
    # into one synthetic "综合" bucket.
    return value


def _latest_complete_report_date(today: date | None = None) -> str:
    """Use the latest fully published annual report for comparable quality ratios."""
    today = today or date.today()
    report_year = today.year - 1 if today >= date(today.year, 4, 30) else today.year - 2
    return f"{report_year}1231"


def _fetch_stock_financial_snapshot(report_date: str | None = None) -> pd.DataFrame:
    import akshare as ak

    report_date = report_date or _latest_complete_report_date()
    raw = ak.stock_yjbb_em(date=report_date)
    if raw.empty:
        return raw
    column_map = {
        "股票代码": "code",
        "所处行业": "raw_sector",
        "净资产收益率": "roe",
        "营业总收入-同比增长": "revenue_growth",
        "净利润-同比增长": "profit_growth",
        "每股经营现金流量": "operating_cashflow_per_share",
        "销售毛利率": "gross_margin",
        "最新公告日期": "announcement_date",
    }
    missing = [column for column in column_map if column not in raw.columns]
    if missing:
        raise RuntimeError(f"A股财务快照字段变化: {missing}")
    frame = raw[list(column_map)].rename(columns=column_map).copy()
    frame["code"] = frame["code"].astype(str).str.zfill(6)
    for column in ("roe", "revenue_growth", "profit_growth", "operating_cashflow_per_share", "gross_margin"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["announcement_date"] = pd.to_datetime(frame["announcement_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return frame.drop_duplicates("code", keep="last")


def sync_full_stock_universe(
    db: Database,
    spot_frame: pd.DataFrame | None = None,
    financial_frame: pd.DataFrame | None = None,
) -> dict:
    """Persist the full source snapshot before applying recommendation filters."""
    batch_id = _identifier("stock-universe")
    started_at = _now()
    with db.connect() as con:
        con.execute(
            """INSERT INTO universe_batches(
            batch_id,asset_type,market,as_of_date,started_at,status,source,source_tier
            ) VALUES (?,?,?,?,?,?,?,?)""",
            (batch_id, "stock", "中国A股", _latest_a_share_session(), started_at, "running", STOCK_SOURCE, "public_aggregator"),
        )
    provider = AkshareProvider()
    failure = None
    try:
        spot = provider.spot() if spot_frame is None else spot_frame.copy()
        quote_source = provider.last_source if spot_frame is None else "injected_frame"
        batch_source = f"AKShare / {quote_source}公开行情；东方财富年度财务快照"
        if spot.empty:
            raise RuntimeError("全市场A股快照为空")
        spot["code"] = spot["code"].astype(str).str.zfill(6)
        spot = spot[spot["code"].str.match(r"^(00|30|60|68|4|8|92)\d{4}$")].copy()
        spot = spot.drop_duplicates("code", keep="last")
        if financial_frame is None:
            financials = _fetch_stock_financial_snapshot()
        else:
            financials = financial_frame.copy()
        if not financials.empty:
            financials["code"] = financials["code"].astype(str).str.zfill(6)
        frame = spot.merge(financials, on="code", how="left") if not financials.empty else spot.copy()
        market_board = frame["code"].map(_board)
        frame["market"] = market_board.map(lambda item: item[0])
        frame["board"] = market_board.map(lambda item: item[1])
        frame["sector"] = frame.get("raw_sector", pd.Series(index=frame.index, dtype=object)).map(normalize_stock_sector)
        if "raw_sector" not in frame:
            frame["raw_sector"] = None
        if "last_price" not in frame:
            frame["last_price"] = np.nan
        for column in (
            "pe", "pb", "market_cap", "amount", "pct_change", "roe", "revenue_growth",
            "profit_growth", "operating_cashflow_per_share", "gross_margin",
        ):
            if column not in frame:
                frame[column] = np.nan
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if "announcement_date" not in frame:
            frame["announcement_date"] = None
        fetched_at = _now()
        rows = [
            (
                batch_id, row.code, row.name, row.market, row.board, row.sector, row.raw_sector,
                row.last_price, row.pe, row.pb, row.market_cap, row.amount, row.pct_change,
                row.roe, row.revenue_growth, row.profit_growth,
                row.operating_cashflow_per_share, row.gross_margin, row.announcement_date,
                batch_source, fetched_at,
            )
            for row in frame.itertuples()
        ]
        coverage = float(frame["roe"].notna().mean()) if len(frame) else 0.0
        status = "complete" if coverage >= 0.60 else "partial"
        message = f"财务字段覆盖率 {coverage:.1%}；分类版本 {STOCK_CLASSIFICATION_VERSION}"
        with db.connect() as con:
            con.executemany(
                """INSERT INTO stock_universe_snapshots(
                batch_id,code,name,market,board,sector,raw_sector,last_price,pe,pb,market_cap,amount,pct_change,
                roe,revenue_growth,profit_growth,operating_cashflow_per_share,gross_margin,
                announcement_date,source,fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
            con.execute(
                """UPDATE universe_batches SET finished_at=?,status=?,total_count=?,stored_count=?,source=?,
                eligible_count=?,failed_count=?,message=? WHERE batch_id=?""",
                (fetched_at, status, len(spot), len(frame), batch_source, int(frame["roe"].notna().sum()), 0, message, batch_id),
            )
        return {"batch_id": batch_id, "status": status, "total": len(spot), "stored": len(frame), "financial_coverage": coverage}
    except Exception as error:
        failure = f"{type(error).__name__}: {error}"
        with db.connect() as con:
            con.execute(
                "UPDATE universe_batches SET finished_at=?,status='failed',failed_count=1,message=? WHERE batch_id=?",
                (_now(), failure, batch_id),
            )
        raise


def _normalise_fund_snapshot(raw: pd.DataFrame, category: str) -> pd.DataFrame:
    column_map = {
        "基金代码": "code", "基金简称": "name", "日期": "nav_date",
        "单位净值": "unit_nav", "累计净值": "cumulative_nav", "近1周": "return_1w",
        "近1月": "return_1m", "近3月": "return_3m", "近6月": "return_6m",
        "近1年": "return_1y", "近2年": "return_2y", "近3年": "return_3y",
        "今年来": "return_ytd", "成立来": "return_since_inception", "手续费": "fee_rate",
    }
    missing = [column for column in column_map if column not in raw.columns]
    if missing:
        raise RuntimeError(f"基金排行字段变化: {missing}")
    frame = raw[list(column_map)].rename(columns=column_map).copy()
    frame["code"] = frame["code"].astype(str).str.zfill(6)
    frame["category"] = category
    frame["nav_date"] = pd.to_datetime(frame["nav_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    numeric = [column for column in column_map.values() if column not in {"code", "name", "nav_date", "fee_rate"}]
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["fee_rate"] = pd.to_numeric(
        frame["fee_rate"].astype(str).str.replace("%", "", regex=False).str.replace("---", "", regex=False),
        errors="coerce",
    ) / 100
    return frame.drop_duplicates("code", keep="last")


def _fetch_fund_quality_snapshot(ak) -> tuple[pd.DataFrame, list[str]]:
    """Fetch bulk rating, manager and scale evidence; each source is optional."""
    errors: list[str] = []
    pieces: list[pd.DataFrame] = []
    try:
        rating = ak.fund_rating_all().copy()
        required = {"代码", "基金经理", "基金公司", "5星评级家数"}
        if not required.issubset(rating.columns):
            raise RuntimeError(f"评级字段变化: {sorted(required - set(rating.columns))}")
        agency_columns = [c for c in ("上海证券", "招商证券", "济安金信", "晨星评级") if c in rating.columns]
        rating["code"] = rating["代码"].astype(str).str.zfill(6)
        rating["fund_company"] = rating["基金公司"].astype(str)
        rating["manager_names_rating"] = rating["基金经理"].astype(str)
        rating["star_rating_count"] = pd.to_numeric(rating["5星评级家数"], errors="coerce")
        if agency_columns:
            rating["rating_score"] = rating[agency_columns].apply(pd.to_numeric, errors="coerce").mean(axis=1)
        else:
            rating["rating_score"] = np.nan
        pieces.append(
            rating[["code", "fund_company", "manager_names_rating", "star_rating_count", "rating_score"]]
            .drop_duplicates("code", keep="last")
        )
    except Exception as error:
        errors.append(f"评级: {type(error).__name__}: {error}")
    try:
        managers = ak.fund_manager_em().copy()
        required = {"姓名", "所属公司", "现任基金代码", "累计从业时间"}
        if not required.issubset(managers.columns):
            raise RuntimeError(f"经理字段变化: {sorted(required - set(managers.columns))}")
        managers["code"] = managers["现任基金代码"].astype(str).str.zfill(6)
        managers["manager_experience_days"] = pd.to_numeric(managers["累计从业时间"], errors="coerce")
        manager_grouped = managers.groupby("code", as_index=False).agg(
            manager_names=("姓名", lambda values: "、".join(dict.fromkeys(str(v) for v in values if pd.notna(v)))),
            manager_company=("所属公司", "last"),
            manager_experience_days=("manager_experience_days", "max"),
        )
        pieces.append(manager_grouped)
    except Exception as error:
        errors.append(f"经理: {type(error).__name__}: {error}")
    try:
        scale = ak.fund_scale_open_sina().copy()
        required = {"基金代码", "单位净值", "最近总份额", "成立日期"}
        if not required.issubset(scale.columns):
            raise RuntimeError(f"规模字段变化: {sorted(required - set(scale.columns))}")
        scale["code"] = scale["基金代码"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
        scale["fund_size_cny"] = pd.to_numeric(scale["单位净值"], errors="coerce") * pd.to_numeric(scale["最近总份额"], errors="coerce")
        scale["inception_date"] = pd.to_datetime(scale["成立日期"], errors="coerce").dt.strftime("%Y-%m-%d")
        pieces.append(scale[["code", "fund_size_cny", "inception_date"]].drop_duplicates("code", keep="last"))
    except Exception as error:
        errors.append(f"规模: {type(error).__name__}: {error}")
    if not pieces:
        return pd.DataFrame({"code": pd.Series(dtype=str)}), errors
    quality = pieces[0]
    for piece in pieces[1:]:
        quality = quality.merge(piece, on="code", how="outer")
    if "manager_names" not in quality:
        quality["manager_names"] = None
    if "manager_names_rating" in quality:
        quality["manager_names"] = quality["manager_names"].replace("", np.nan).combine_first(quality["manager_names_rating"])
    if "fund_company" not in quality:
        quality["fund_company"] = None
    if "manager_company" in quality:
        quality["fund_company"] = quality["fund_company"].replace("nan", np.nan).combine_first(quality["manager_company"])
    return quality.drop_duplicates("code", keep="last"), errors


def sync_full_fund_universe(
    db: Database,
    category_frames: dict[str, pd.DataFrame] | None = None,
    master_frame: pd.DataFrame | None = None,
) -> dict:
    """Persist every fund share returned by the declared category endpoints."""
    import akshare as ak

    batch_id = _identifier("fund-universe")
    started_at = _now()
    with db.connect() as con:
        con.execute(
            """INSERT INTO universe_batches(
            batch_id,asset_type,market,as_of_date,started_at,status,source,source_tier
            ) VALUES (?,?,?,?,?,?,?,?)""",
            (batch_id, "fund", "中国公募基金", date.today().isoformat(), started_at, "running", FUND_SOURCE, "public_aggregator"),
        )
    frames = []
    failures = []
    try:
        if master_frame is not None:
            master = master_frame.copy()
        elif category_frames is None:
            master = ak.fund_name_em()
        else:
            master = pd.concat(
                [frame[["基金代码", "基金简称"]] for frame in category_frames.values()],
                ignore_index=True,
            ).drop_duplicates("基金代码")
            master["基金类型"] = "测试分类"
        required_master = {"基金代码", "基金简称", "基金类型"}
        if not required_master.issubset(master.columns):
            raise RuntimeError(f"基金主数据字段变化: {sorted(required_master - set(master.columns))}")
        master = master[["基金代码", "基金简称", "基金类型"]].copy()
        master["基金代码"] = master["基金代码"].astype(str).str.zfill(6)
        master = master.drop_duplicates("基金代码", keep="last")
    except Exception as error:
        with db.connect() as con:
            con.execute(
                "UPDATE universe_batches SET finished_at=?,status='failed',failed_count=1,message=? WHERE batch_id=?",
                (_now(), f"基金主数据失败: {type(error).__name__}: {error}", batch_id),
            )
        raise
    for category in FUND_CATEGORIES:
        try:
            raw = category_frames[category].copy() if category_frames is not None else ak.fund_open_fund_rank_em(symbol=category)
            frames.append(_normalise_fund_snapshot(raw, category))
        except Exception as error:
            failures.append(f"{category}: {type(error).__name__}: {error}")
    if not frames:
        with db.connect() as con:
            con.execute(
                "UPDATE universe_batches SET finished_at=?,status='failed',failed_count=?,message=? WHERE batch_id=?",
                (_now(), len(failures), "; ".join(failures), batch_id),
            )
        raise RuntimeError("全部基金分类接口均失败")
    frame = pd.concat(frames, ignore_index=True)
    if category_frames is None:
        quality, quality_errors = _fetch_fund_quality_snapshot(ak)
        frame = frame.merge(quality, on="code", how="left")
        quality_source = "AKShare / 东方财富基金评级与经理 / 新浪基金规模"
    else:
        quality_errors = []
        quality_source = "injected_fixture"
        frame["fund_company"] = frame["name"].astype(str).str[:3]
        frame["manager_names"] = "测试经理"
        frame["manager_experience_days"] = 1800.0
        frame["star_rating_count"] = 2.0
        frame["rating_score"] = 4.0
        frame["fund_size_cny"] = 2_000_000_000.0
        frame["inception_date"] = "2020-01-01"
    for column in ("fund_company", "manager_names", "manager_experience_days", "star_rating_count", "rating_score", "fund_size_cny", "inception_date"):
        if column not in frame:
            frame[column] = np.nan
    frame["quality_source"] = quality_source
    source_dates = pd.to_datetime(frame["nav_date"], errors="coerce")
    as_of_date = source_dates.max().strftime("%Y-%m-%d") if source_dates.notna().any() else date.today().isoformat()
    fetched_at = _now()
    rows = [
        (
            batch_id, row.code, row.name, row.category, row.nav_date, row.unit_nav,
            row.cumulative_nav, row.return_1w, row.return_1m, row.return_3m,
            row.return_6m, row.return_1y, row.return_2y, row.return_3y,
            row.return_ytd, row.return_since_inception, row.fee_rate, FUND_SOURCE, fetched_at,
            row.fund_company, row.manager_names, row.manager_experience_days,
            row.star_rating_count, row.rating_score, row.fund_size_cny,
            row.inception_date, row.quality_source,
        )
        for row in frame.itertuples()
    ]
    status = "complete" if not failures else "partial"
    with db.connect() as con:
        con.execute("UPDATE fund_master SET status='not_in_latest_source'")
        con.executemany(
            """INSERT INTO fund_master(code,name,fund_type,source,first_seen_at,last_seen_at,status)
            VALUES (?,?,?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET
            name=excluded.name,fund_type=excluded.fund_type,source=excluded.source,
            last_seen_at=excluded.last_seen_at,status=excluded.status""",
            [
                (row["基金代码"], row["基金简称"], row["基金类型"], FUND_SOURCE, fetched_at, fetched_at, "active_in_source")
                for _, row in master.iterrows()
            ],
        )
        con.executemany(
            """INSERT INTO fund_universe_snapshots(
            batch_id,code,name,category,nav_date,unit_nav,cumulative_nav,return_1w,return_1m,
            return_3m,return_6m,return_1y,return_2y,return_3y,return_ytd,
            return_since_inception,fee_rate,source,fetched_at,fund_company,manager_names,
            manager_experience_days,star_rating_count,rating_score,fund_size_cny,
            inception_date,quality_source
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        con.execute(
            """UPDATE universe_batches SET finished_at=?,status=?,as_of_date=?,total_count=?,stored_count=?,
            eligible_count=?,failed_count=?,message=? WHERE batch_id=?""",
            (
                fetched_at, status, as_of_date, len(master), len(frame), int(frame["return_1y"].notna().sum()),
                len(failures), "; ".join(failures) if failures else (
                    "六类基金份额快照完整；质量源异常 " + str(len(quality_errors))
                ),
                batch_id,
            ),
        )
    return {"batch_id": batch_id, "status": status, "total": len(master), "stored": len(frame), "failed_categories": failures}


def _load_stock_history(db: Database, code: str) -> pd.DataFrame:
    frame = db.query_df("SELECT * FROM daily_prices WHERE code=? ORDER BY trade_date", (code,))
    if len(frame) >= 150:
        return frame
    provider = AkshareProvider()
    fresh = provider.history(code, date.today() - timedelta(days=560), date.today(), "qfq")
    if not fresh.empty:
        db.upsert_prices(fresh, provider.last_source or "akshare_unknown", "qfq")
    return db.query_df("SELECT * FROM daily_prices WHERE code=? ORDER BY trade_date", (code,))


def _price_features(history: pd.DataFrame) -> dict[str, float]:
    if len(history) < 150:
        raise RuntimeError("有效交易日不足150日")
    history = history.sort_values("trade_date").drop_duplicates("trade_date").tail(260)
    close = pd.to_numeric(history["close"], errors="coerce").dropna()
    if len(close) < 150:
        raise RuntimeError("有效收盘价不足150日")
    daily = close.pct_change()
    trailing = close.tail(120)
    drawdown = trailing / trailing.cummax() - 1
    return {
        "close": float(close.iloc[-1]),
        "return_3m": float(close.iloc[-1] / close.iloc[-61] - 1),
        "return_1y": float(close.iloc[-1] / close.iloc[0] - 1),
        "volatility": float(daily.tail(120).std() * np.sqrt(252)),
        "max_drawdown": float(drawdown.min()),
        "data_as_of": str(pd.to_datetime(history["trade_date"]).max().date()),
    }


def _family_name(name: str) -> str:
    value = re.sub(r"[（(].*?[）)]$", "", str(name)).strip()
    value = re.sub(r"(?:A|B|C|D|E|I|R|Y)(?:类|份额)?$", "", value, flags=re.I)
    return value.strip(" -_")


def _share_class_preference(name: str) -> int:
    """Prefer A shares for long-horizon research; zero front-load is not zero cost."""
    value = str(name).strip()
    if re.search(r"A(?:类|份额)?$", value, flags=re.I):
        return 2
    if re.search(r"C(?:类|份额)?$", value, flags=re.I):
        return 0
    return 1


def _frame_hash(frame: pd.DataFrame, sort_by: tuple[str, ...] = ("code",)) -> str:
    columns = [column for column in sort_by if column in frame.columns]
    stable = frame.sort_values(columns).reset_index(drop=True).copy() if columns else frame.reset_index(drop=True).copy()
    payload = stable.to_json(orient="split", date_format="iso", double_precision=12)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _combined_input_hash(snapshot: pd.DataFrame, history_hashes: dict[str, str]) -> str:
    payload = _frame_hash(snapshot) + json.dumps(sorted(history_hashes.items()), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _code_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _insert_recommendation_run(
    db: Database,
    run_id: str,
    batch_id: str,
    asset_type: str,
    market: str,
    as_of_date: str,
    status: str,
    model_version: str,
    universe_count: int,
    eligible_count: int,
    sections: list[dict],
    scores: list[dict],
    message: str | None = None,
    model_config: dict | None = None,
    input_hash: str | None = None,
    exclusions: list[dict] | None = None,
) -> None:
    published_count = sum(int(row["recommended"]) for row in scores)
    with db.connect() as con:
        if status == "complete":
            con.execute(
                """UPDATE recommendation_runs SET status='superseded',
                message=COALESCE(message || '；','') || '同类型同数据日已有更新的完整批次'
                WHERE asset_type=? AND as_of_date=? AND status='complete'""",
                (asset_type, as_of_date),
            )
        con.execute(
            """INSERT INTO recommendation_runs(
            run_id,universe_batch_id,asset_type,market,as_of_date,created_at,status,
            model_version,universe_count,eligible_count,section_count,published_count,message,
            model_config_json,input_hash,code_hash
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id, batch_id, asset_type, market, as_of_date, _now(), status,
                model_version, universe_count, eligible_count, len(sections), published_count, message,
                json.dumps(model_config or {}, ensure_ascii=False, sort_keys=True), input_hash, _code_hash(),
            ),
        )
        con.executemany(
            """INSERT INTO recommendation_sections(
            run_id,section,total_count,analyzed_count,qualified_count,published_count,status,message
            ) VALUES (?,?,?,?,?,?,?,?)""",
            [
                (
                    run_id, item["section"], item["total_count"], item["analyzed_count"],
                    item["qualified_count"], item["published_count"], item["status"], item.get("message"),
                )
                for item in sections
            ],
        )
        con.executemany(
            """INSERT INTO recommendation_scores(
            run_id,asset_type,section,code,name,rank,score,confidence,eligible,recommended,
            last_value,return_3m,return_1y,risk_metric,data_as_of,reasons,risks,
            exclusion_reason,source
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    run_id, row["asset_type"], row["section"], row["code"], row["name"],
                    row.get("rank"), row.get("score"), row["confidence"], int(row["eligible"]),
                    int(row["recommended"]), row.get("last_value"), row.get("return_3m"),
                    row.get("return_1y"), row.get("risk_metric"), row.get("data_as_of"),
                    row.get("reasons"), row.get("risks"), row.get("exclusion_reason"), row["source"],
                )
                for row in scores
            ],
        )
        con.executemany(
            """INSERT INTO recommendation_exclusions(
            run_id,asset_type,section,code,name,stage,reason
            ) VALUES (?,?,?,?,?,?,?)""",
            [
                (
                    run_id, row["asset_type"], row["section"], row["code"], row["name"],
                    row["stage"], row["reason"],
                )
                for row in (exclusions or [])
            ],
        )


def analyze_stock_batch(
    db: Database,
    batch_id: str,
    workers: int = 6,
    candidates_per_section: int = 15,
) -> dict:
    batch = db.query_df("SELECT * FROM universe_batches WHERE batch_id=?", (batch_id,))
    if batch.empty or batch.iloc[0]["asset_type"] != "stock":
        raise ValueError("请选择有效的股票宇宙批次")
    if batch.iloc[0]["status"] != "complete":
        raise RuntimeError("股票宇宙批次不完整，拒绝发布正式推荐")
    snapshot = db.query_df("SELECT * FROM stock_universe_snapshots WHERE batch_id=?", (batch_id,))
    as_of_date = pd.Timestamp(batch.iloc[0]["as_of_date"])
    run_id = _identifier("stock-rec")
    snapshot["section"] = snapshot["sector"].fillna("行业待分类")
    name = snapshot["name"].astype(str)
    base_gate = (
        ~name.str.upper().str.contains("ST|退", regex=True)
        & snapshot["pe"].between(0, 80)
        & (snapshot["roe"] >= 8)
        & (snapshot["operating_cashflow_per_share"] > 0)
        & (snapshot["amount"] >= 50_000_000)
        & (snapshot["section"] != "行业待分类")
        # The current public-history route does not reliably cover Beijing codes.
        # They remain in the full snapshot with an explicit model exclusion.
        & (snapshot["board"] != "北交所")
    )
    def stock_prefilter_reason(row) -> str:
        reasons = []
        if "ST" in str(row.name).upper() or "退" in str(row.name): reasons.append("风险警示或退市标识")
        if pd.isna(row.pe) or not 0 < float(row.pe) <= 80: reasons.append("PE不在(0,80]或缺失")
        if pd.isna(row.roe) or float(row.roe) < 8: reasons.append("ROE低于8%或缺失")
        if pd.isna(row.operating_cashflow_per_share) or float(row.operating_cashflow_per_share) <= 0: reasons.append("每股经营现金流不为正或缺失")
        if pd.isna(row.amount) or float(row.amount) < 50_000_000: reasons.append("成交额低于5000万元或缺失")
        if row.section == "行业待分类": reasons.append("行业待分类")
        if row.board == "北交所": reasons.append("免费历史行情链路暂不稳定")
        return "；".join(reasons) or "未通过预筛硬门槛"

    exclusions = [
        {
            "asset_type": "stock", "section": row.section, "code": row.code, "name": row.name,
            "stage": "prefilter", "reason": stock_prefilter_reason(row),
        }
        for row in snapshot.loc[~base_gate].itertuples()
    ]
    preliminary = snapshot[base_gate].copy()
    preliminary["pre_score"] = (
        0.35 * _rank(preliminary["roe"])
        + 0.20 * _rank(preliminary["revenue_growth"])
        + 0.20 * _rank(preliminary["profit_growth"])
        + 0.15 * _rank(preliminary["pe"], False)
        + 0.10 * _rank(preliminary["amount"])
    )
    deep = (
        preliminary.sort_values(["section", "pre_score", "amount"], ascending=[True, False, False])
        .groupby("section", group_keys=False)
        .head(candidates_per_section)
    )
    deep_codes = set(deep["code"])
    exclusions.extend(
        {
            "asset_type": "stock", "section": row.section, "code": row.code, "name": row.name,
            "stage": "depth_limit", "reason": f"同板块预评分未进入前{candidates_per_section}",
        }
        for row in preliminary.loc[~preliminary["code"].isin(deep_codes)].itertuples()
    )
    histories: dict[str, dict] = {}
    history_hashes: dict[str, str] = {}
    failures: dict[str, str] = {}
    expected_exclusions: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(_load_stock_history, db, code): code for code in deep["code"]}
        for future in as_completed(futures):
            code = futures[future]
            try:
                history = future.result().copy()
                history = history[pd.to_datetime(history["trade_date"], errors="coerce") <= as_of_date]
                history_hashes[code] = _frame_hash(history, ("trade_date",))
                histories[code] = _price_features(history)
            except Exception as error:
                detail = f"{type(error).__name__}: {error}"
                if "不足150" in str(error):
                    expected_exclusions[code] = "上市历史不足150个有效交易日"
                else:
                    failures[code] = detail
    deep_lookup = deep.set_index("code")[["section", "name"]].to_dict("index")
    exclusions.extend(
        {
            "asset_type": "stock", "section": deep_lookup[code]["section"], "code": code,
            "name": deep_lookup[code]["name"], "stage": "history_short", "reason": reason,
        }
        for code, reason in expected_exclusions.items()
    )
    exclusions.extend(
        {
            "asset_type": "stock", "section": deep_lookup[code]["section"], "code": code,
            "name": deep_lookup[code]["name"], "stage": "data_failure", "reason": reason,
        }
        for code, reason in failures.items()
    )
    enriched = deep[deep["code"].isin(histories)].copy()
    if not enriched.empty:
        feature_frame = pd.DataFrame.from_dict(histories, orient="index").reset_index(names="code")
        enriched = enriched.merge(feature_frame, on="code", how="inner")
    scores: list[dict] = []
    sections: list[dict] = []
    for section, all_section in snapshot.groupby("section"):
        section_deep = enriched[enriched["section"] == section].copy() if not enriched.empty else pd.DataFrame()
        attempted = deep[deep["section"] == section]
        expected_count = int(attempted["code"].isin(expected_exclusions).sum())
        unexpected_count = int(attempted["code"].isin(failures).sum())
        coverage = (len(section_deep) + expected_count) / len(attempted) if len(attempted) else 1.0
        # Zero pre-qualified names is a valid 0/5 outcome, not a data failure.
        section_status = "complete" if (not len(attempted) or coverage >= 0.95) and unexpected_count == 0 else "partial"
        if not section_deep.empty:
            section_deep["score"] = 100 * (
                0.18 * _shrunk_rank(section_deep["roe"])
                + 0.07 * _shrunk_rank(section_deep["operating_cashflow_per_share"])
                + 0.05 * _shrunk_rank(section_deep["gross_margin"])
                + 0.10 * _shrunk_rank(section_deep["revenue_growth"])
                + 0.05 * _shrunk_rank(section_deep["profit_growth"])
                + 0.20 * _shrunk_rank(section_deep["pe"], False)
                + 0.15 * _shrunk_rank(section_deep["return_3m"])
                + 0.08 * _shrunk_rank(section_deep["volatility"], False)
                + 0.07 * _shrunk_rank(section_deep["max_drawdown"])
                + 0.05 * _shrunk_rank(section_deep["amount"])
            )
            key_fields = ["roe", "operating_cashflow_per_share", "revenue_growth", "profit_growth", "pe", "return_3m", "volatility", "max_drawdown"]
            section_deep["confidence"] = section_deep[key_fields].notna().mean(axis=1) * 100
            section_deep["eligible"] = (
                (section_deep["confidence"] >= 75)
                & (section_deep["score"] >= 55)
                & (section_deep["revenue_growth"] >= 0)
                & (section_deep["profit_growth"] >= 0)
                & (section_deep["return_3m"] >= -0.10)
                & (section_deep["return_1y"] >= -0.15)
                & (section_deep["max_drawdown"] >= -0.40)
                & (section_deep["volatility"] <= 0.80)
            )
            qualified = section_deep[section_deep["eligible"]].sort_values(
                ["score", "amount", "code"], ascending=[False, False, True]
            )
            if section_status == "complete":
                published_codes = set(qualified.head(5)["code"])
            else:
                published_codes = set()
            rank_by_code = {code: rank for rank, code in enumerate(qualified["code"], 1)}
            for row in section_deep.itertuples():
                reasons = f"ROE {row.roe:.1f}%；近3月 {row.return_3m:.1%}；PE {row.pe:.1f}"
                risks = f"120日最大回撤 {row.max_drawdown:.1%}；年化波动 {row.volatility:.1%}"
                scores.append(
                    {
                        "asset_type": "stock", "section": section, "code": row.code, "name": row.name,
                        "rank": rank_by_code.get(row.code), "score": row.score, "confidence": row.confidence,
                        "eligible": bool(row.eligible), "recommended": row.code in published_codes,
                        "last_value": row.close, "return_3m": row.return_3m, "return_1y": row.return_1y,
                        "risk_metric": row.max_drawdown, "data_as_of": row.data_as_of,
                        "reasons": reasons, "risks": risks,
                        "exclusion_reason": None if row.eligible else "未通过得分、增长、动量、置信度或风险硬门槛",
                        "source": STOCK_SOURCE,
                    }
                )
            qualified_count = len(qualified)
            published_count = len(published_codes)
        else:
            qualified_count = 0
            published_count = 0
        sections.append(
            {
                "section": section, "total_count": len(all_section), "analyzed_count": len(section_deep) + expected_count,
                "qualified_count": qualified_count, "published_count": published_count,
                "status": section_status,
                "message": f"深度池 {len(attempted)}，有效历史 {len(section_deep)}，历史不足 {expected_count}，意外失败 {unexpected_count}，最多发布5只；不凑数",
            }
        )
    run_status = "complete" if not failures and sections and all(item["status"] == "complete" for item in sections if item["section"] != "行业待分类") else "partial"
    if run_status != "complete":
        for row in scores:
            row["recommended"] = False
    _insert_recommendation_run(
        db, run_id, batch_id, "stock", "中国A股", str(batch.iloc[0]["as_of_date"]),
        run_status, f"{STOCK_MODEL_VERSION}-deep{candidates_per_section}", len(snapshot), sum(int(row["eligible"]) for row in scores),
        sections, scores, f"历史取数失败 {len(failures)}；历史不足排除 {len(expected_exclusions)}；分类版本 {STOCK_CLASSIFICATION_VERSION}",
        model_config={
            "classification": STOCK_CLASSIFICATION_VERSION,
            "prefilter": {"exclude_name_markers": ["ST", "退"], "exclude_board": ["北交所"], "pe": [0, 80], "roe_min": 8, "operating_cashflow_per_share_min": 0, "amount_min": 50_000_000},
            "pre_weights": {"roe": 0.35, "revenue_growth": 0.20, "profit_growth": 0.20, "pe": 0.15, "amount": 0.10},
            "deep_per_section": candidates_per_section,
            "weights": {"roe": 0.18, "cashflow": 0.07, "gross_margin": 0.05, "revenue_growth": 0.10, "profit_growth": 0.05, "pe": 0.20, "return_3m": 0.15, "volatility": 0.08, "max_drawdown": 0.07, "amount": 0.05},
            "publish": {"score_min": 55, "confidence_min": 75, "revenue_growth_min": 0, "profit_growth_min": 0, "return_3m_min": -0.10, "return_1y_min": -0.15, "max_drawdown_min": -0.40, "volatility_max": 0.80, "per_section_max": 5},
        },
        input_hash=_combined_input_hash(snapshot, history_hashes),
        exclusions=exclusions,
    )
    return {"run_id": run_id, "status": run_status, "sections": len(sections), "published": sum(int(row["recommended"]) for row in scores), "failures": failures}


def analyze_fund_batch(
    db: Database,
    batch_id: str,
    candidates_per_section: int = 30,
    workers: int = 6,
) -> dict:
    batch = db.query_df("SELECT * FROM universe_batches WHERE batch_id=?", (batch_id,))
    if batch.empty or batch.iloc[0]["asset_type"] != "fund":
        raise ValueError("请选择有效的基金宇宙批次")
    if batch.iloc[0]["status"] != "complete":
        raise RuntimeError("基金宇宙批次不完整，拒绝发布正式推荐")
    snapshot = db.query_df("SELECT * FROM fund_universe_snapshots WHERE batch_id=?", (batch_id,))
    run_id = _identifier("fund-rec")
    snapshot["family"] = snapshot["name"].map(_family_name)
    nav_dates = pd.to_datetime(snapshot["nav_date"], errors="coerce")
    batch_date = pd.Timestamp(batch.iloc[0]["as_of_date"])
    base_gate = (
        snapshot["return_1y"].notna()
        & snapshot["return_2y"].notna()
        & nav_dates.ge(batch_date - pd.Timedelta(days=10))
        & snapshot["unit_nav"].gt(0)
    )
    exclusions = [
        {
            "asset_type": "fund", "section": row.category, "code": row.code, "name": row.name,
            "stage": "prefilter", "reason": "近1/2年收益缺失、净值陈旧或单位净值无效",
        }
        for row in snapshot.loc[~base_gate].itertuples()
    ]
    preliminary = snapshot[base_gate].copy()
    bond_mask = preliminary["category"] == "债券型"
    bond_gate = (
        ~bond_mask
        | (
            preliminary["return_1y"].between(0, 20)
            & preliminary["return_2y"].between(0, 45)
        )
    )
    exclusions.extend(
        {
            "asset_type": "fund", "section": row.category, "code": row.code, "name": row.name,
            "stage": "category_gate", "reason": "债券型历史收益超出当前风险类别边界",
        }
        for row in preliminary.loc[~bond_gate].itertuples()
    )
    preliminary = preliminary[bond_gate].copy()
    preliminary["pre_score"] = (
        0.30 * _rank(preliminary["return_1y"])
        + 0.25 * _rank(preliminary["return_2y"])
        + 0.15 * _rank(preliminary["return_3y"])
        + 0.12 * _rank(preliminary["rating_score"])
        + 0.08 * _rank(preliminary["manager_experience_days"])
        + 0.10 * _rank(preliminary["fund_size_cny"])
    )
    preliminary["share_preference"] = preliminary["name"].map(_share_class_preference)
    representatives = (
        preliminary.sort_values(
            ["category", "family", "share_preference", "pre_score", "code"],
            ascending=[True, True, False, False, True],
        )
        .drop_duplicates(["category", "family"], keep="first")
    )
    representative_codes = set(representatives["code"])
    exclusions.extend(
        {
            "asset_type": "fund", "section": row.category, "code": row.code, "name": row.name,
            "stage": "share_class_dedup", "reason": "同基金家族份额归并，长期研究优先A类",
        }
        for row in preliminary.loc[~preliminary["code"].isin(representative_codes)].itertuples()
    )
    deep = (
        representatives.sort_values(["category", "pre_score", "code"], ascending=[True, False, True])
        .groupby("category", group_keys=False)
        .head(candidates_per_section)
    )
    deep_codes = set(deep["code"])
    exclusions.extend(
        {
            "asset_type": "fund", "section": row.category, "code": row.code, "name": row.name,
            "stage": "depth_limit", "reason": f"同类预评分未进入前{candidates_per_section}",
        }
        for row in representatives.loc[~representatives["code"].isin(deep_codes)].itertuples()
    )
    history_metrics: dict[str, dict] = {}
    history_hashes: dict[str, str] = {}
    failures: dict[str, str] = {}
    def load_fund_metrics(code: str) -> dict:
        history = cached_fund_history(db, code, refresh=False, purpose="analysis")
        history = history[pd.to_datetime(history["date"], errors="coerce") <= batch_date].copy()
        if history.empty or history.attrs.get("nav_kind") != "累计净值" or len(history) < 200:
            raise RuntimeError("没有足够累计净值历史")
        nav = history["nav"].astype(float)
        daily = nav.pct_change()
        one_year_base = history.loc[history["date"] <= history["date"].iloc[-1] - pd.DateOffset(years=1), "nav"]
        history_hashes[code] = _frame_hash(history, ("date",))
        return {
            "last_value_history": float(nav.iloc[-1]),
            "volatility": float(daily.tail(250).std() * np.sqrt(250)),
            "max_drawdown": float((nav / nav.cummax() - 1).min()),
            "history_return_1y": float(nav.iloc[-1] / one_year_base.iloc[-1] - 1) if not one_year_base.empty else np.nan,
            "data_as_of_history": str(history["date"].max().date()),
        }

    # AKShare's fund endpoint embeds a JavaScript runtime that is not thread-safe
    # on Windows. Keep this path sequential; scheduled reliability matters more
    # than shaving a minute off a nightly job.
    for code in deep["code"].unique():
        try:
            history_metrics[code] = load_fund_metrics(code)
        except Exception as error:
            failures[code] = f"{type(error).__name__}: {error}"
    deep_lookup = deep.set_index("code")[["category", "name"]].to_dict("index")
    exclusions.extend(
        {
            "asset_type": "fund", "section": deep_lookup[code]["category"], "code": code,
            "name": deep_lookup[code]["name"], "stage": "data_failure", "reason": reason,
        }
        for code, reason in failures.items()
    )
    scores: list[dict] = []
    sections: list[dict] = []
    for category, all_section in snapshot.groupby("category"):
        attempted = deep[deep["category"] == category]
        valid = attempted[attempted["code"].isin(history_metrics)].copy()
        unexpected_count = int(attempted["code"].isin(failures).sum())
        coverage = len(valid) / len(attempted) if len(attempted) else 0.0
        section_status = "complete" if len(attempted) and coverage >= 0.80 and unexpected_count == 0 else "partial"
        if not valid.empty:
            metrics = pd.DataFrame.from_dict(history_metrics, orient="index").reset_index(names="code")
            valid = valid.merge(metrics, on="code", how="inner")
            valid["score"] = 100 * (
                0.18 * _rank(valid["return_1y"])
                + 0.16 * _rank(valid["return_2y"])
                + 0.10 * _rank(valid["return_3y"])
                + 0.12 * _rank(valid["history_return_1y"])
                + 0.12 * _rank(valid["volatility"], False)
                + 0.14 * _rank(valid["max_drawdown"])
                + 0.08 * _rank(valid["rating_score"])
                + 0.05 * _rank(valid["manager_experience_days"])
                + 0.05 * _rank(valid["fund_size_cny"])
            )
            key_fields = [
                "return_1y", "return_2y", "return_3y", "history_return_1y", "volatility",
                "max_drawdown", "rating_score", "manager_experience_days", "fund_size_cny",
            ]
            valid["confidence"] = valid[key_fields].notna().mean(axis=1) * 100
            risk_limits = {
                "债券型": (-0.15, 0.15), "FOF": (-0.25, 0.30), "混合型": (-0.35, 0.40),
                "股票型": (-0.40, 0.50), "指数型": (-0.40, 0.50), "QDII": (-0.40, 0.50),
            }
            drawdown_floor, volatility_ceiling = risk_limits.get(category, (-0.40, 0.50))
            valid["eligible"] = (
                (valid["confidence"] >= 78)
                & (valid["score"] >= 55)
                & (valid["max_drawdown"] >= drawdown_floor)
                & (valid["volatility"] <= volatility_ceiling)
            )
            qualified = valid[valid["eligible"]].sort_values(["score", "code"], ascending=[False, True])
            selected_codes = []
            company_counts: dict[str, int] = {}
            if section_status == "complete":
                for candidate in qualified.itertuples():
                    company = str(candidate.fund_company).strip() if pd.notna(candidate.fund_company) else f"unknown-{candidate.code}"
                    if company_counts.get(company, 0) >= 2:
                        continue
                    selected_codes.append(candidate.code)
                    company_counts[company] = company_counts.get(company, 0) + 1
                    if len(selected_codes) == 5:
                        break
            published_codes = set(selected_codes)
            rank_by_code = {code: rank for rank, code in enumerate(qualified["code"], 1)}
            for row in valid.itertuples():
                rating_text = "暂无" if pd.isna(row.rating_score) else f"{row.rating_score:.1f}"
                manager_text = "暂无" if pd.isna(row.manager_experience_days) else f"{row.manager_experience_days / 365:.1f}年"
                size_text = "暂无" if pd.isna(row.fund_size_cny) else f"{row.fund_size_cny / 1e8:.1f}亿元"
                scores.append(
                    {
                        "asset_type": "fund", "section": category, "code": row.code, "name": row.name,
                        "rank": rank_by_code.get(row.code), "score": row.score, "confidence": row.confidence,
                        "eligible": bool(row.eligible), "recommended": row.code in published_codes,
                        "last_value": row.unit_nav, "return_3m": row.return_3m / 100 if pd.notna(row.return_3m) else np.nan,
                        "return_1y": row.return_1y / 100 if pd.notna(row.return_1y) else np.nan,
                        "risk_metric": row.max_drawdown, "data_as_of": row.nav_date,
                        "reasons": (
                            f"近1年 {row.return_1y:.1f}%；评级均值 "
                            f"{rating_text}；经理从业 {manager_text}；规模约 {size_text}"
                        ),
                        "risks": (
                            f"历史最大回撤 {row.max_drawdown:.1%}；年化波动 {row.volatility:.1%}；"
                            "评级和历史业绩不代表未来，公开数据仍缺完整总费率与实时持仓归因"
                        ),
                        "exclusion_reason": None if row.eligible else "未通过得分、置信度或风险硬门槛",
                        "source": FUND_SOURCE,
                    }
                )
            qualified_count = len(qualified)
            published_count = len(published_codes)
        else:
            qualified_count = 0
            published_count = 0
        sections.append(
            {
                "section": category, "total_count": len(all_section), "analyzed_count": len(valid),
                "qualified_count": qualified_count, "published_count": published_count,
                "status": section_status,
                "message": f"深度池 {len(attempted)}，累计净值有效 {len(valid)}，意外失败 {unexpected_count}，同基金份额去重，同公司最多2只，每类最多发布5只",
            }
        )
    run_status = "complete" if not failures and sections and all(item["status"] == "complete" for item in sections) else "partial"
    if run_status != "complete":
        for row in scores:
            row["recommended"] = False
    _insert_recommendation_run(
        db, run_id, batch_id, "fund", "中国公募基金", str(batch.iloc[0]["as_of_date"]),
        run_status, f"{FUND_MODEL_VERSION}-deep{candidates_per_section}", len(snapshot), sum(int(row["eligible"]) for row in scores),
        sections, scores,
        f"基金主数据 {int(batch.iloc[0]['total_count'])}；六类可排名份额快照 {len(snapshot)}；"
        f"累计净值深度取数失败 {len(failures)}；不使用单位净值计算总回报",
        model_config={
            "categories": list(FUND_CATEGORIES), "deep_per_category": candidates_per_section,
            "dedup": "fund_family_prefer_A", "company_cap": 2,
            "prefilter": {"required_returns": ["1y", "2y"], "nav_lag_days_max": 10, "bond_return_1y": [0, 20], "bond_return_2y": [0, 45]},
            "weights": {"return_1y": 0.18, "return_2y": 0.16, "return_3y": 0.10, "history_return_1y": 0.12, "volatility": 0.12, "max_drawdown": 0.14, "rating": 0.08, "manager_experience": 0.05, "fund_size": 0.05},
            "publish": {"score_min": 55, "confidence_min": 78, "per_category_max": 5},
            "risk_limits": {"债券型": [-0.15, 0.15], "FOF": [-0.25, 0.30], "混合型": [-0.35, 0.40], "股票型": [-0.40, 0.50], "指数型": [-0.40, 0.50], "QDII": [-0.40, 0.50]},
        },
        input_hash=_combined_input_hash(snapshot, history_hashes),
        exclusions=exclusions,
    )
    return {"run_id": run_id, "status": run_status, "sections": len(sections), "published": sum(int(row["recommended"]) for row in scores), "failures": failures}


def latest_complete_batch(db: Database, asset_type: str) -> pd.Series | None:
    frame = db.query_df(
        """SELECT * FROM universe_batches WHERE asset_type=? AND status='complete'
        ORDER BY started_at DESC LIMIT 1""",
        (asset_type,),
    )
    return None if frame.empty else frame.iloc[0]


def recommendation_history(db: Database, asset_type: str | None = None) -> pd.DataFrame:
    if asset_type:
        return db.query_df(
            "SELECT * FROM recommendation_runs WHERE asset_type=? ORDER BY as_of_date DESC,created_at DESC",
            (asset_type,),
        )
    return db.query_df("SELECT * FROM recommendation_runs ORDER BY created_at DESC")


def formal_recommendation_trail(db: Database, asset_type: str, code: str) -> pd.DataFrame:
    """Return only published recommendations from completed, auditable runs."""
    return db.query_df(
        """SELECT r.as_of_date,r.run_id,s.section,s.rank,s.score,s.reasons,s.risks,s.data_as_of
        FROM recommendation_scores s
        JOIN recommendation_runs r ON r.run_id=s.run_id
        WHERE s.asset_type=? AND s.code=? AND s.recommended=1 AND r.status='complete'
        ORDER BY r.as_of_date DESC,r.created_at DESC""",
        (asset_type, code),
    )
