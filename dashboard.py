from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from stock_picker.analysis import (
    cached_fund_history,
    fund_rank,
    fund_profile,
    fund_summary,
    fund_technical_indicators,
    stock_financials,
    stock_health,
    stock_history,
    stock_summary,
    stock_technical_indicators,
)
from stock_picker.config import load_settings
from stock_picker.db import Database
from stock_picker.events import add_custom_event, delete_custom_event, due_reminders, event_local_time, seed_official_events, upcoming_events
from stock_picker.multi_asset import (
    MARKET_GROUPS,
    asset_summary,
    cached_asset_history,
    cached_treasury_yield_curve,
    fundamental_timeseries,
    latest_yield_curve,
    market_snapshot,
    search_assets, unified_search,
    treasury_yield_curve,
)
from stock_picker.pipeline import run_selection, sync_data
from stock_picker.recommendations import (
    FUND_MODEL_VERSION,
    STOCK_CLASSIFICATION_VERSION,
    STOCK_MODEL_VERSION,
    analyze_fund_batch,
    analyze_stock_batch,
    formal_recommendation_trail,
    recommendation_history,
    sync_full_fund_universe,
    sync_full_stock_universe,
)
from stock_picker.jobs import exclusive_job
from stock_picker.maintenance import sync_multi_asset_data
from stock_picker.global_screen import GLOBAL_EQUITY_UNIVERSE, cached_fundamentals, screen_global_equities
from stock_picker.portfolio import (
    add_holding, add_transaction, allocation_drift, delete_holding, delete_transaction, get_investor_profile,
    holding_return_matrix, list_holdings, list_transactions, portfolio_risk_summary,
    save_investor_profile, save_target_allocations, stress_portfolio, transaction_ledger_summary, value_holdings,
)
from stock_picker.watchlist import (
    add_note,
    delete_note,
    list_notes,
    list_watchlist,
    remove_watchlist_item,
    save_watchlist_item,
)
from stock_picker.semiconductor_battle import (
    INTRADAY_SOURCE,
    SEMICONDUCTOR_MARKETS,
    aggregate_battle,
    fetch_semiconductor_battle,
)
from stock_picker.market_radar import (
    INDEX_UNIVERSES,
    INSTRUMENT_UNIVERSES,
    REGIONS,
    SECTOR_UNIVERSES,
    breadth,
    fetch_radar_group,
    normalized_curves,
    parse_custom_symbols,
)


ROOT = Path(__file__).parent
settings = load_settings(ROOT / "config.toml")
db = Database(settings.database)
seed_official_events(db)

st.set_page_config(page_title="知衡投资研究台", page_icon="◈", layout="wide", initial_sidebar_state="auto")
st.markdown(
    """
    <style>
    :root { --ink:#17211b; --muted:#66736b; --green:#176b55; --line:#dfe5e0; --paper:#f7f8f5; }
    .stApp { background:var(--paper); color:var(--ink); }
    .block-container { max-width:1280px; padding-top:2rem; }
    section[data-testid="stSidebar"] { background:#13241d; }
    section[data-testid="stSidebar"] * { color:#e9f1ed !important; }
    section[data-testid="stSidebar"] .stButton button { border:0; background:transparent; text-align:left; justify-content:flex-start; padding:.38rem .7rem; }
    section[data-testid="stSidebar"] .stButton button:hover,
    section[data-testid="stSidebar"] .stButton button:focus { background:#274138 !important; }
    section[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"] { background:#315b4b !important; }
    section[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"]:hover,
    section[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"]:focus { background:#3b715d !important; }
    section[data-testid="stSidebar"] [data-testid="stExpander"] details,
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary { background:transparent !important; }
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover,
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary:focus,
    section[data-testid="stSidebar"] [data-testid="stExpander"] details[open] > summary { background:#274138 !important; }
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary:focus-visible { outline:3px solid #ffbf47 !important; outline-offset:2px; }
    [data-testid="stMetric"] { background:white; border:1px solid var(--line); padding:15px 17px; border-radius:10px; }
    div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:10px; overflow:hidden; }
    .page-title { font-size:2rem; font-weight:720; letter-spacing:-.04em; margin:.1rem 0 .3rem; }
    .subtitle { color:var(--muted); margin-bottom:1.3rem; }
    .source { display:inline-block; padding:4px 9px; background:#edf3ef; color:#3f5d50; border-radius:6px; font-size:.78rem; margin:.3rem .25rem .7rem 0; }
    .event { background:white; border:1px solid var(--line); padding:13px 15px; margin:8px 0; border-radius:10px; }
    .event-high { border-left:4px solid #b5483a; }
    .event-medium { border-left:4px solid #b2872f; }
    .battle-hero { color:#fff; border-radius:16px; padding:20px 22px; margin:.35rem 0 1rem; box-shadow:0 10px 28px rgba(20,30,25,.12); }
    .battle-hero.bull { background:linear-gradient(125deg,#5f1822 0%,#a92f3e 58%,#d55752 100%); }
    .battle-hero.bear { background:linear-gradient(125deg,#0f3f35 0%,#13715d 58%,#3f9d7e 100%); }
    .battle-hero.neutral { background:linear-gradient(125deg,#4a4030 0%,#8d713b 58%,#ba9448 100%); }
    .battle-hero-head,.battle-hero-main,.battle-card-head,.battle-card-price,.battle-card-foot { display:flex; align-items:center; justify-content:space-between; gap:12px; }
    .battle-hero-head { font-size:.78rem; color:rgba(255,255,255,.82); }
    .battle-live { display:inline-flex; align-items:center; gap:7px; font-weight:700; letter-spacing:.08em; }
    .battle-live::before { content:""; width:8px; height:8px; border-radius:50%; background:#fff; box-shadow:0 0 0 5px rgba(255,255,255,.16); animation:battlePulse 1.6s ease-out infinite; }
    @keyframes battlePulse { 0% { opacity:1; transform:scale(.9); } 70% { opacity:.65; transform:scale(1.2); } 100% { opacity:1; transform:scale(.9); } }
    .battle-hero-main { margin:18px 0 14px; align-items:flex-end; }
    .battle-hero-kicker { display:block; font-size:.8rem; color:rgba(255,255,255,.75); margin-bottom:3px; }
    .battle-hero-label { font-size:2rem; font-weight:760; letter-spacing:-.04em; line-height:1.05; }
    .battle-hero-score { font-size:2.5rem; font-weight:780; line-height:1; font-variant-numeric:tabular-nums; }
    .battle-meter { height:8px; background:rgba(255,255,255,.22); border-radius:99px; overflow:hidden; }
    .battle-meter span { display:block; height:100%; background:#fff; border-radius:99px; }
    .battle-meter-labels { display:flex; justify-content:space-between; margin-top:7px; color:rgba(255,255,255,.72); font-size:.72rem; }
    .battle-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:.25rem 0 1rem; }
    .battle-card { --accent:#9a7938; background:#fff; color:#17211b; border:1px solid #e2e6e2; border-top:4px solid var(--accent); border-radius:13px; padding:15px 16px 13px; box-shadow:0 3px 12px rgba(23,33,27,.05); min-width:0; }
    .battle-card.bull { --accent:#bd3e49; }
    .battle-card.bear { --accent:#168069; }
    .battle-card.neutral { --accent:#a57c31; }
    .battle-name { font-size:1rem; font-weight:720; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .battle-symbol,.battle-state { color:#758078; font-size:.72rem; }
    .battle-card-price { align-items:baseline; margin:13px 0 4px; }
    .battle-last { font-size:1.5rem; font-weight:760; letter-spacing:-.035em; font-variant-numeric:tabular-nums; white-space:nowrap; }
    .battle-change { font-size:.9rem; font-weight:720; color:var(--accent); white-space:nowrap; }
    .battle-card-foot { border-top:1px solid #edf0ed; margin-top:11px; padding-top:10px; color:#5d6961; font-size:.75rem; }
    .battle-verdict { color:var(--accent); font-weight:740; }
    .battle-signals { display:grid; grid-template-columns:repeat(3,1fr); gap:5px; margin-top:11px; }
    .battle-signal { background:#f5f7f5; border-radius:7px; padding:7px 5px; text-align:center; }
    .battle-signal span { display:block; color:#7b857e; font-size:.62rem; margin-bottom:2px; }
    .battle-signal b { font-size:.76rem; font-variant-numeric:tabular-nums; }
    .battle-section-title { font-size:1.05rem; font-weight:720; margin:1.15rem 0 .45rem; }
    .radar-overview { display:grid; grid-template-columns:1.5fr repeat(3,1fr); gap:1px; background:#31433a; border-radius:14px; overflow:hidden; margin:.5rem 0 1rem; color:#fff; }
    .radar-stat { background:#16251e; padding:15px 17px; min-width:0; }
    .radar-stat:first-child { background:linear-gradient(125deg,#183028,#294d3f); }
    .radar-stat span { display:block; color:#aebbb4; font-size:.72rem; margin-bottom:4px; }
    .radar-stat b { display:block; font-size:1.18rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
    .radar-up { color:#e46b70 !important; }
    .radar-down { color:#4fbd91 !important; }
    .radar-cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:11px; margin:.25rem 0 1rem; }
    .empty { background:white; border:1px dashed #bcc8c0; padding:24px; border-radius:10px; color:var(--muted); }
    .foot { color:var(--muted); font-size:.78rem; border-top:1px solid var(--line); padding-top:1rem; margin-top:2rem; }
    h2, h3 { letter-spacing:-.02em; }
    button:focus-visible, input:focus-visible, a:focus-visible { outline:3px solid #ffbf47 !important; outline-offset:2px; }
    .stButton button, [data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-primary"] { min-height:44px; }
    @media (max-width: 768px) {
      .block-container { padding:1rem .75rem 2rem; }
      .page-title { font-size:1.55rem; }
      [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
      [data-testid="column"] { min-width:calc(50% - .5rem) !important; flex:1 1 calc(50% - .5rem) !important; }
      [data-testid="stMetric"] { padding:11px; }
      .source, .foot, .event small { font-size:.875rem; }
      .battle-grid { grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px; }
      .battle-hero { padding:17px 16px; }
      .battle-hero-label { font-size:1.55rem; }
      .battle-hero-score { font-size:2rem; }
      .battle-card { padding:13px 12px 11px; }
      .radar-overview { grid-template-columns:repeat(2,1fr); }
    }
    @media (max-width: 420px) {
      [data-testid="column"] { min-width:100% !important; flex-basis:100% !important; }
      .battle-grid { grid-template-columns:1fr; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


PAGES = {
    "核心流程": ["拉取信息", "分析", "推荐", "诊股/诊基"],
    "工作台": ["今日", "全局搜索", "全球市场", "半导体多空战况", "自选资产"],
    "市场雷达": ["多层市场雷达"],
    "我的组合": ["投资约束", "交易记录", "持仓", "目标配置", "资产配置", "集中度风险", "资产相关性", "压力情景"],
    "股票": ["A股选股", "全球选股", "全球证券分析", "全球基本面", "A股财务", "研究笔记"],
    "基金与ETF": ["国内基金排行", "国内基金分析", "全球ETF"],
    "债券": ["国债利率", "债券ETF"],
    "商品": ["黄金与商品"],
    "事件提醒": ["重要事件", "自定义提醒"],
    "系统": ["数据管理", "评分说明"],
}


def title(text: str, subtitle: str) -> None:
    st.title(text)
    st.markdown(f'<div class="subtitle">{escape(subtitle)}</div>', unsafe_allow_html=True)


def source_badge(source: str, as_of: str | None = None) -> None:
    suffix = f" · 数据截至 {as_of}" if as_of else ""
    st.markdown(f'<span class="source">来源：{source}{suffix}</span>', unsafe_allow_html=True)


def pct(value: float) -> str:
    return "暂无" if pd.isna(value) else f"{value:.2%}"


def stock_name(code: str) -> str:
    frame = db.query_df("SELECT name FROM instruments WHERE code=?", (code,))
    if frame.empty:
        frame = db.query_df(
            "SELECT name FROM stock_universe_snapshots WHERE code=? ORDER BY fetched_at DESC LIMIT 1",
            (code,),
        )
    return str(frame.iloc[0]["name"]) if not frame.empty else code


def current_code() -> str:
    value = str(st.session_state.get("active_stock", "000001")).strip()
    return value[-6:].zfill(6)


def set_active_code() -> None:
    st.session_state["active_stock"] = str(st.session_state["sidebar_stock"])[-6:].zfill(6)


ASSET_TYPE_LABELS = {
    "global_stock":"全球股票", "a_share":"A股", "fund":"基金", "etf":"ETF",
    "bond":"债券/债券ETF", "commodity":"商品", "cash":"现金", "index":"指数", "stock":"A股（旧记录）",
}


def set_research_asset(symbol: str) -> None:
    symbol = symbol.upper()
    st.session_state["active_symbol"] = symbol
    if symbol.endswith((".SS", ".SZ")) and symbol[:6].isdigit():
        st.session_state["active_stock"] = symbol[:6]
    st.session_state["page"] = "全球证券分析"


def snapshot_actions(frame: pd.DataFrame, key: str) -> None:
    if frame.empty:
        return
    selected = st.selectbox("选择下一步研究的资产", frame.symbol, key=f"asset-{key}", format_func=lambda value: f"{frame.loc[frame.symbol == value, 'name'].iloc[0]} · {value}")
    a, b = st.columns(2)
    if a.button("进入分析", key=f"research-{key}", width="stretch"):
        set_research_asset(selected)
        st.rerun()
    if b.button("加入自选", key=f"watch-{key}", width="stretch"):
        row = frame[frame.symbol == selected].iloc[0]
        type_map = {"全球股指":"index", "商品":"commodity", "债券ETF":"bond", "全球ETF":"etf", "etf":"etf"}
        save_watchlist_item(db, selected, row["name"], type_map.get(key, "global_stock"))
        st.success("已加入自选资产。")


def a_share_selector(key: str) -> str:
    current = current_code()
    instruments = db.query_df("SELECT code, name FROM instruments ORDER BY code")
    if instruments.empty:
        code = st.text_input("A股代码", value=current, max_chars=6, key=f"a-code-{key}")
    else:
        values = instruments.code.tolist()
        index = values.index(current) if current in values else 0
        code = st.selectbox("A股标的", values, index=index, key=f"a-select-{key}", format_func=lambda value: f"{value} · {instruments.loc[instruments.code == value, 'name'].iloc[0]}")
    st.session_state["active_stock"] = str(code).zfill(6)
    return str(code).zfill(6)


def load_stock(code: str, refresh: bool = False) -> pd.DataFrame:
    try:
        with st.spinner("正在读取真实行情…"):
            return stock_history(db, code, refresh=refresh)
    except Exception as error:
        st.error(f"没有获取到真实行情：{error}")
        return pd.DataFrame()


def stock_header(code: str, refresh_key: str) -> tuple[pd.DataFrame, dict | None]:
    left, right = st.columns([5, 1])
    left.subheader(f"{stock_name(code)} · {code}")
    refresh = right.button("联网刷新", key=refresh_key, width="stretch")
    frame = load_stock(code, refresh)
    if frame.empty:
        st.markdown('<div class="empty">本地没有记录，联网也未取得数据。本页不会显示估算或示例数值。</div>', unsafe_allow_html=True)
        return frame, None
    as_of = frame["trade_date"].max().strftime("%Y-%m-%d")
    source_badge("AKShare（东方财富，失败时回退腾讯行情）", as_of)
    return frame, stock_summary(frame)


def add_to_watchlist(code: str, key: str) -> None:
    if st.button("＋ 加入自选", key=key):
        save_watchlist_item(db, code, stock_name(code))
        st.success("已加入自选股。")


def render_events(frame: pd.DataFrame, limit: int = 20) -> None:
    if frame.empty:
        st.markdown('<div class="empty">该时间范围没有已核验事件。</div>', unsafe_allow_html=True)
        return
    for row in frame.head(limit).itertuples():
        urgency = "今天" if row.days_left == 0 else f"{row.days_left} 天后"
        css = "event-high" if row.importance == "高" else "event-medium"
        safe_url = escape(str(row.source_url), quote=True) if row.source_url else ""
        link = f' · <a href="{safe_url}" target="_blank" rel="noopener noreferrer">查看官方来源</a>' if safe_url.startswith("https://") else ""
        safe_title = escape(str(row.title))
        safe_description = escape(str(row.description or ""))
        safe_region = escape(str(row.region))
        safe_importance = escape(str(row.importance))
        verification = escape(str(getattr(row, "verification_status", "未标注")))
        verified_at = escape(str(getattr(row, "last_verified", "") or "未知"))
        event_time = escape(str(getattr(row, "event_time", "") or "时间待官方确定"))
        event_timezone = escape(str(getattr(row, "event_timezone", "") or "时区按来源"))
        shanghai = event_local_time(str(row.event_date), getattr(row, "event_time", None), getattr(row, "event_timezone", None))
        local_label = f" · 上海时间 {escape(shanghai)}" if shanghai else ""
        st.markdown(
            f'<div class="event {css}"><b>{row.event_date}　{event_time}　{safe_title}</b><br><small>{urgency} · {safe_region} · {event_timezone}{local_label} · {safe_importance}重要性 · {verification} · 核验于 {verified_at}{link}</small><br>{safe_description}</div>',
            unsafe_allow_html=True,
        )


def _signed_pct(value: float) -> str:
    return "暂无" if pd.isna(value) else f"{value:+.2%}"


@st.fragment(run_every="15s")
def render_semiconductor_battle() -> None:
    auto_refresh = st.session_state.get("semiconductor_auto_refresh", True)
    force_refresh = st.session_state.pop("semiconductor_force_refresh", False)
    payload = st.session_state.get("semiconductor_payload")
    if auto_refresh or force_refresh or payload is None:
        try:
            with st.spinner("正在同步四个市场的 1 分钟行情……"):
                payload = fetch_semiconductor_battle()
            st.session_state["semiconductor_payload"] = payload
            st.session_state["semiconductor_last_fetch"] = datetime.now().astimezone().isoformat(timespec="seconds")
        except Exception as error:
            st.error(f"本轮行情同步失败：{error}")
            if payload is None:
                return

    summary, frames, errors = payload
    if summary.empty:
        st.error("四个市场均未取得有效行情，本页不会生成替代数据。")
        for name, error in errors.items():
            st.caption(f"{name}：{error}")
        return

    aggregate = aggregate_battle(summary)
    aggregate_class = "bull" if aggregate["score"] >= 8 else "bear" if aggregate["score"] <= -8 else "neutral"
    meter_width = max(0.0, min(100.0, (aggregate["score"] + 100) / 2))
    fetched = st.session_state.get("semiconductor_last_fetch", "未知")
    try:
        fetched_label = pd.Timestamp(fetched).strftime("%H:%M:%S")
    except Exception:
        fetched_label = "刚刚"
    st.markdown(
        f"""
        <div class="battle-hero {aggregate_class}">
          <div class="battle-hero-head">
            <span class="battle-live">LIVE · 15秒刷新</span>
            <span>{escape(fetched_label)} · 覆盖 {aggregate['coverage']}/4</span>
          </div>
          <div class="battle-hero-main">
            <div><span class="battle-hero-kicker">半导体综合多空</span><div class="battle-hero-label">{escape(aggregate['label'])}</div></div>
            <div class="battle-hero-score">{aggregate['score']:+.1f}</div>
          </div>
          <div class="battle-meter"><span style="width:{meter_width:.1f}%"></span></div>
          <div class="battle-meter-labels"><span>空方 -100</span><span>多方 {aggregate['bulls']} · 胶着 {aggregate['coverage'] - aggregate['bulls'] - aggregate['bears']} · 空方 {aggregate['bears']}</span><span>多方 +100</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cards = []
    for row in summary.itertuples():
        card_class = "bull" if row.score >= 8 else "bear" if row.score <= -8 else "neutral"
        price = f"{row.last:,.0f}" if abs(row.last) >= 10_000 else f"{row.last:,.2f}"
        change = _signed_pct(row.session_return)
        momentum = _signed_pct(row.return_5m)
        rsi = "—" if pd.isna(row.rsi14) else f"{row.rsi14:.1f}"
        pressure = "—" if pd.isna(row.pressure) else f"{row.pressure:+.1%}"
        session = "交易中" if row.session_state == "交易中" else "已收盘"
        cards.append(
            f"""
            <div class="battle-card {card_class}">
              <div class="battle-card-head"><div><div class="battle-name">{escape(str(row.name))}</div><div class="battle-symbol">{escape(str(row.symbol))}</div></div><span class="battle-state">{session}</span></div>
              <div class="battle-card-price"><span class="battle-last">{price}</span><span class="battle-change">{change}</span></div>
              <div class="battle-signals">
                <div class="battle-signal"><span>近5分钟</span><b>{momentum}</b></div>
                <div class="battle-signal"><span>RSI14</span><b>{rsi}</b></div>
                <div class="battle-signal"><span>量价压力</span><b>{pressure}</b></div>
              </div>
              <div class="battle-card-foot"><span class="battle-verdict">{escape(str(row.label))}</span><b>{row.score:+.1f}</b></div>
            </div>
            """.strip()
        )
    st.markdown(f'<div class="battle-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

    display = summary[
        [
            "name", "symbol", "currency", "last", "session_high", "session_low", "session_volume",
            "session_return", "return_5m", "rsi14",
            "volume_ratio", "pressure", "score", "label", "session_state",
            "freshness", "last_timestamp",
        ]
    ].rename(
        columns={
            "name": "战场", "symbol": "代码", "currency": "币种", "last": "最新价",
            "session_high": "时段高", "session_low": "时段低", "session_volume": "成交量",
            "session_return": "本时段涨跌",
            "return_5m": "近5分钟", "rsi14": "RSI14", "volume_ratio": "量比脉冲",
            "pressure": "量价压力", "score": "多空分", "label": "判断", "session_state": "市场状态",
            "freshness": "时效", "last_timestamp": "市场当地时间",
        }
    )
    normalized: dict[str, pd.Series] = {}
    for row in summary.itertuples():
        data = frames.get(row.name)
        if data is None or data.empty:
            continue
        base = row.previous_close if pd.notna(row.previous_close) and row.previous_close else data.close.iloc[0]
        normalized[row.name] = (data.close.reset_index(drop=True) / base - 1) * 100
    if normalized:
        st.markdown('<div class="battle-section-title">本交易时段走势</div>', unsafe_allow_html=True)
        st.line_chart(pd.DataFrame(normalized), height=300, y_label="较昨收涨跌（%）", x_label="分钟序号（各市场并非同一时区）")

    with st.expander("查看完整交易数据与指标拆解"):
        st.dataframe(
            display,
            hide_index=True,
            width="stretch",
            column_config={
                "最新价": st.column_config.NumberColumn(format="localized"),
                "时段高": st.column_config.NumberColumn(format="localized"),
                "时段低": st.column_config.NumberColumn(format="localized"),
                "成交量": st.column_config.NumberColumn(format="compact"),
                "本时段涨跌": st.column_config.NumberColumn(format="percent"),
                "近5分钟": st.column_config.NumberColumn(format="percent"),
                "RSI14": st.column_config.NumberColumn(format="%.1f"),
                "量比脉冲": st.column_config.NumberColumn(format="%.2f"),
                "量价压力": st.column_config.NumberColumn(format="percent"),
                "多空分": st.column_config.ProgressColumn(min_value=-100, max_value=100, format="%.1f"),
            },
        )
        chosen = st.selectbox("拆解标的", summary["name"].tolist(), key="semiconductor_detail")
        selected_row = summary[summary.name == chosen].iloc[0]
        selected = frames[chosen]
        chart_columns = [column for column in ["close", "vwap", "ema5", "ema20"] if column in selected and selected[column].notna().any()]
        chart = selected.set_index("timestamp")[chart_columns].rename(columns={"close":"价格", "vwap":"VWAP", "ema5":"EMA5", "ema20":"EMA20"})
        chart.attrs = {}
        left, right = st.columns([2, 1])
        left.line_chart(chart, height=300)
        selected_rsi = "暂无" if pd.isna(selected_row["rsi14"]) else f"{selected_row['rsi14']:.1f}"
        right.markdown(
            f"**{selected_row['label']} · {selected_row['score']:+.1f}**  \n"
            f"本时段：{_signed_pct(selected_row['session_return'])}  \n"
            f"5 / 15 / 60分钟：{' / '.join(_signed_pct(selected_row[key]) for key in ('return_5m', 'return_15m', 'return_60m'))}  \n"
            f"RSI14：{selected_rsi}"
        )
        components = selected.attrs.get("components", pd.DataFrame())
        if not components.empty:
            component_display = components[["indicator", "evidence", "weight", "contribution"]].rename(
                columns={"indicator":"指标", "evidence":"现场证据", "weight":"权重", "contribution":"分数贡献"}
            ).sort_values("分数贡献", ascending=False)
            st.dataframe(
                component_display,
                hide_index=True,
                width="stretch",
                column_config={"权重": st.column_config.NumberColumn(format="%.0f"), "分数贡献": st.column_config.NumberColumn(format="%+.1f")},
            )

    if errors:
        st.warning("部分标的本轮失败，综合分只使用成功标的：" + "；".join(f"{name}（{error}）" for name, error in errors.items()))
    st.caption(f"来源：{INTRADAY_SOURCE} · 四个标的统一按美股正常交易时段比较，综合分不构成交易建议。")


def _compact_amount(value: float, currency: str | None = None) -> str:
    if pd.isna(value):
        return "—"
    absolute = abs(value)
    for scale, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if absolute >= scale:
            return f"{value / scale:+.1f}{suffix} {currency or ''}".strip()
    return f"{value:+.0f} {currency or ''}".strip()


def _render_radar_cards(summary: pd.DataFrame) -> None:
    cards = []
    for row in summary.itertuples():
        change = row.session_return
        card_class = "bull" if pd.notna(change) and change > 0.00005 else "bear" if pd.notna(change) and change < -0.00005 else "neutral"
        price = f"{row.last:,.0f}" if abs(row.last) >= 10_000 else f"{row.last:,.2f}"
        flow = "—" if pd.isna(row.flow_strength) else f"{row.flow_strength:+.1%}"
        as_of = pd.Timestamp(row.as_of).strftime("%H:%M") if row.as_of else "—"
        cards.append(
            f"""
            <div class="battle-card {card_class}">
              <div class="battle-card-head"><div><div class="battle-name">{escape(str(row.name))}</div><div class="battle-symbol">{escape(str(row.symbol))}</div></div><span class="battle-state">{escape(str(row.currency or ''))}</span></div>
              <div class="battle-card-price"><span class="battle-last">{price}</span><span class="battle-change">{_signed_pct(change)}</span></div>
              <div class="battle-signals">
                <div class="battle-signal"><span>近5分钟</span><b>{_signed_pct(row.return_5m)}</b></div>
                <div class="battle-signal"><span>近30分钟</span><b>{_signed_pct(row.return_30m)}</b></div>
                <div class="battle-signal"><span>资金压力*</span><b>{flow}</b></div>
              </div>
              <div class="battle-card-foot"><span>{as_of}</span><b>{row.bars} 根1分钟K</b></div>
            </div>
            """.strip()
        )
    st.markdown(f'<div class="radar-cards">{"".join(cards)}</div>', unsafe_allow_html=True)


@st.fragment(run_every="20s")
def render_market_radar(view: str, region: str, universe: dict[str, str]) -> None:
    auto_refresh = st.session_state.get("radar_auto_refresh", True)
    force_refresh = st.session_state.pop("radar_force_refresh", False)
    payloads = st.session_state.setdefault("radar_payloads", {})
    payload_key = (view, region, tuple(universe.items()))
    payload = payloads.get(payload_key)
    if auto_refresh or force_refresh or payload is None:
        try:
            with st.spinner("正在拉取当前层级的一分钟行情……"):
                payload = fetch_radar_group(universe)
            payloads[payload_key] = payload
            st.session_state["radar_last_fetch"] = datetime.now().astimezone().isoformat(timespec="seconds")
        except Exception as error:
            st.error(f"本轮市场雷达刷新失败：{error}")
            if payload is None:
                return

    summary, frames, errors = payload
    if summary.empty:
        st.error("当前选择没有取得有效行情，不生成替代数字。")
        if errors:
            st.caption("；".join(f"{name}：{error}" for name, error in errors.items()))
        return

    market_breadth = breadth(summary)
    average = market_breadth["average_return"]
    average_class = "radar-up" if pd.notna(average) and average > 0 else "radar-down" if pd.notna(average) and average < 0 else ""
    fetched = st.session_state.get("radar_last_fetch", "")
    fetched_label = pd.Timestamp(fetched).strftime("%H:%M:%S") if fetched else "刚刚"
    st.markdown(
        f"""
        <div class="radar-overview">
          <div class="radar-stat"><span>{escape(region)} · {escape(view)}</span><b>LIVE · {fetched_label}</b></div>
          <div class="radar-stat"><span>平均涨跌</span><b class="{average_class}">{_signed_pct(average)}</b></div>
          <div class="radar-stat"><span>上涨 / 下跌</span><b><i class="radar-up">{market_breadth['advances']}</i> / <i class="radar-down">{market_breadth['declines']}</i></b></div>
          <div class="radar-stat"><span>有效覆盖</span><b>{len(summary)} / {len(universe)}</b></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _render_radar_cards(summary)

    curves = normalized_curves(summary, frames)
    if not curves.empty:
        st.markdown('<div class="battle-section-title">实时涨跌走势</div>', unsafe_allow_html=True)
        st.line_chart(curves, height=330, y_label="较昨收涨跌（%）", x_label="本交易时段分钟序号")

    if view == "板块":
        left, right = st.columns(2)
        returns = summary.set_index("name")["session_return"].sort_values() * 100
        left.markdown("#### 板块强弱")
        left.bar_chart(returns, horizontal=True, height=330, x_label="本时段涨跌（%）")
        flow = summary.dropna(subset=["flow_strength"]).set_index("name")["flow_strength"].sort_values() * 100
        right.markdown("#### 量价资金压力代理")
        if flow.empty:
            right.info("这些代理没有可靠成交量，因此不显示资金方向。")
        else:
            right.bar_chart(flow, horizontal=True, height=330, x_label="最近30分钟压力（%）")
        st.caption("*资金压力不是交易所净流入：它用最近30分钟K线方向×成交额估算成交偏向；正值偏主动买入，负值偏主动卖出。")

    if view in {"基金 / 个股", "自定义"} and len(summary) == 1:
        row = summary.iloc[0]
        frame = frames[row["name"]].copy()
        volume = pd.to_numeric(frame.volume, errors="coerce").fillna(0)
        typical = frame[["high", "low", "close"]].mean(axis=1).fillna(frame.close)
        frame["VWAP"] = (typical * volume).cumsum() / volume.cumsum().replace(0, pd.NA)
        price_chart = frame.set_index("timestamp")[["close", "VWAP"]].rename(columns={"close":"价格"})
        price_chart.attrs = {}
        a, b = st.columns([2, 1])
        a.markdown("#### 价格与VWAP")
        a.line_chart(price_chart, height=300)
        b.markdown("#### 现场数据")
        b.markdown(
            f"最高：**{row['session_high']:,.2f}**  \n"
            f"最低：**{row['session_low']:,.2f}**  \n"
            f"成交量：**{_compact_amount(row['session_volume'])}**  \n"
            f"资金压力代理：**{_compact_amount(row['flow_proxy'], row['currency'])}**"
        )

    with st.expander("查看完整行情与数据口径"):
        display = summary[
            ["name", "symbol", "currency", "last", "session_return", "return_5m", "return_30m", "session_volume", "flow_proxy", "flow_strength", "flow_kind", "as_of"]
        ].rename(
            columns={"name":"名称", "symbol":"代码", "currency":"币种", "last":"最新", "session_return":"本时段", "return_5m":"5分钟", "return_30m":"30分钟", "session_volume":"成交量", "flow_proxy":"资金压力金额", "flow_strength":"资金压力比例", "flow_kind":"资金口径", "as_of":"市场当地时间"}
        )
        st.dataframe(
            display,
            hide_index=True,
            width="stretch",
            column_config={
                "最新": st.column_config.NumberColumn(format="localized"),
                "本时段": st.column_config.NumberColumn(format="percent"),
                "5分钟": st.column_config.NumberColumn(format="percent"),
                "30分钟": st.column_config.NumberColumn(format="percent"),
                "成交量": st.column_config.NumberColumn(format="compact"),
                "资金压力金额": st.column_config.NumberColumn(format="compact"),
                "资金压力比例": st.column_config.NumberColumn(format="percent"),
            },
        )
        st.caption("价格与成交量来自 Yahoo Finance Chart API；资金压力字段是本地确定性计算，AI不参与。")
    if errors:
        st.warning("部分代码本轮失败：" + "；".join(f"{name}（{error}）" for name, error in errors.items()))


if "page" not in st.session_state:
    st.session_state["page"] = "推荐"
if "active_stock" not in st.session_state:
    st.session_state["active_stock"] = "000001"
if "active_symbol" not in st.session_state:
    st.session_state["active_symbol"] = "^GSPC"

with st.sidebar:
    st.markdown("## ◈ 知衡")
    st.caption("全球多资产 · 只呈现真实数据")
    for group, pages in PAGES.items():
        with st.expander(group, expanded=st.session_state["page"] in pages or group == "核心流程"):
            for item in pages:
                if st.button(item, key=f"nav-{item}", width="stretch", type="primary" if st.session_state["page"] == item else "secondary"):
                    st.session_state["page"] = item
                    st.rerun()
    st.divider()
    prices_status = db.query_df("SELECT MAX(trade_date) latest FROM daily_prices").iloc[0]["latest"]
    st.caption(f"行情截至：{prices_status or '尚未初始化'}")

page = st.session_state["page"]


if page == "拉取信息":
    title("拉取信息", "先保存声明范围内的全市场快照，再筛选；存储范围与推荐范围严格分离。")
    st.info(
        "免费模式的全量范围是：沪深北在数据源中可见的全部A股，以及公开基金排行覆盖的六类境内公募基金份额。"
        "全球页面仍是精选研究池；没有授权证券主数据前不会宣称全球全量。"
    )
    batches = db.query_df(
        "SELECT * FROM universe_batches ORDER BY started_at DESC LIMIT 100"
    )
    latest_stock = batches[batches.asset_type == "stock"].head(1) if not batches.empty else pd.DataFrame()
    latest_fund = batches[batches.asset_type == "fund"].head(1) if not batches.empty else pd.DataFrame()
    a, b, c, d = st.columns(4)
    a.metric("最新股票快照", int(latest_stock.iloc[0].stored_count) if not latest_stock.empty else 0)
    b.metric("股票批次状态", str(latest_stock.iloc[0].status) if not latest_stock.empty else "尚未拉取")
    c.metric("最新基金份额快照", int(latest_fund.iloc[0].stored_count) if not latest_fund.empty else 0)
    d.metric("基金批次状态", str(latest_fund.iloc[0].status) if not latest_fund.empty else "尚未拉取")
    stock_col, fund_col = st.columns(2)
    with stock_col:
        st.subheader("A股全市场")
        st.caption("保存全部源端代码、行情横截面和最新已完整披露财务快照；ST等仍入库，只在分析时排除。")
        if st.button("拉取A股全量快照", type="primary", width="stretch"):
            try:
                with exclusive_job(db, ROOT / "data" / ".writer.lock", "stock_universe_full") as job:
                    with st.spinner("正在拉取全市场快照和财务快照，首次可能需要数十秒……"):
                        result = sync_full_stock_universe(db)
                    job["succeeded"] = result["stored"]
                    job["failed"] = 0 if result["status"] == "complete" else 1
                    job["message"] = f"batch={result['batch_id']} coverage={result['financial_coverage']:.1%}"
                st.success(f"股票批次已保存：{result['stored']}只；财务覆盖率 {result['financial_coverage']:.1%}。")
                st.rerun()
            except Exception as error:
                st.error(f"股票快照失败，失败批次已留痕：{error}")
    with fund_col:
        st.subheader("境内公募基金")
        st.caption("保存股票型、混合型、债券型、指数型、FOF、QDII全量份额快照；A/C份额在推荐时归并。")
        if st.button("拉取六类基金绩效快照", type="primary", width="stretch"):
            try:
                with exclusive_job(db, ROOT / "data" / ".writer.lock", "fund_universe_full") as job:
                    with st.spinner("正在拉取六类基金全量排行，通常需要几十秒……"):
                        result = sync_full_fund_universe(db)
                    job["succeeded"] = result["stored"]
                    job["failed"] = len(result["failed_categories"])
                    job["message"] = f"batch={result['batch_id']}"
                st.success(f"基金主数据 {result['total']} 只；六类绩效快照 {result['stored']} 条。")
                st.rerun()
            except Exception as error:
                st.error(f"基金快照失败，失败批次已留痕：{error}")
    st.subheader("数据批次")
    if batches.empty:
        st.markdown('<div class="empty">尚无全量快照。点击上方按钮开始；系统不会展示示例批次。</div>', unsafe_allow_html=True)
    else:
        show = batches[["as_of_date", "batch_id", "asset_type", "status", "stored_count", "eligible_count", "failed_count", "source", "message"]].rename(
            columns={"as_of_date":"数据日", "batch_id":"批次", "asset_type":"类型", "status":"状态", "stored_count":"已存", "eligible_count":"关键字段有效", "failed_count":"失败", "source":"来源", "message":"说明"}
        )
        st.dataframe(show, hide_index=True, width="stretch")
    st.warning("公开聚合源不等同于交易所授权数据商。每个批次都保留真实来源和抓取时间；接口不完整时批次为 partial，不能发布正式推荐。")

elif page == "分析":
    title("分析", "从一个已冻结的完整数据批次运行模型；相同批次和模型版本可重复核对。")
    asset_label = st.segmented_control("分析对象", ["股票", "基金"], default="股票")
    asset_type = "stock" if asset_label == "股票" else "fund"
    batches = db.query_df(
        """SELECT * FROM universe_batches WHERE asset_type=?
        ORDER BY CASE WHEN status='complete' THEN 0 ELSE 1 END, started_at DESC""",
        (asset_type,),
    )
    if batches.empty:
        st.warning("没有对应的全量数据批次，请先进入“拉取信息”。")
    else:
        batch_id = st.selectbox(
            "数据批次",
            batches.batch_id,
            format_func=lambda value: (
                f"{batches.loc[batches.batch_id == value, 'as_of_date'].iloc[0]} · "
                f"{batches.loc[batches.batch_id == value, 'status'].iloc[0]} · {value}"
            ),
        )
        selected_batch = batches[batches.batch_id == batch_id].iloc[0]
        x, y, z, w = st.columns(4)
        x.metric("快照记录", int(selected_batch.stored_count))
        y.metric("关键字段有效", int(selected_batch.eligible_count))
        z.metric("批次状态", selected_batch.status)
        w.metric("模型版本", STOCK_MODEL_VERSION if asset_type == "stock" else FUND_MODEL_VERSION)
        st.caption(str(selected_batch.message or ""))
        if selected_batch.status != "complete":
            st.error("这个批次不完整。可以检查失败原因或重新拉取，但不能据此发布正式候选。")
        run_label = "分析股票并生成板块候选" if asset_type == "stock" else "分析基金并生成分类候选"
        if st.button(run_label, type="primary", disabled=selected_batch.status != "complete"):
            try:
                with exclusive_job(db, ROOT / "data" / ".writer.lock", f"recommend_{asset_type}") as job:
                    with st.spinner("正在补齐入围资产历史数据、计算指标并冻结推荐批次……"):
                        result = analyze_stock_batch(db, batch_id) if asset_type == "stock" else analyze_fund_batch(db, batch_id)
                    job["succeeded"] = result["published"]
                    job["failed"] = len(result["failures"])
                    job["message"] = f"run={result['run_id']} status={result['status']}"
                if result["status"] == "complete":
                    st.success(f"分析完成：{result['sections']}个板块/类别，共发布 {result['published']} 只研究候选。")
                else:
                    st.warning("分析批次为 partial，结果已留痕但不会发布正式候选；请处理失败项后重跑。")
                st.rerun()
            except Exception as error:
                st.error(f"分析未完成：{error}")
    st.subheader("分析历史")
    runs = recommendation_history(db, asset_type)
    if runs.empty:
        st.caption("尚无分析批次。")
    else:
        st.dataframe(
            runs[["as_of_date", "run_id", "status", "model_version", "universe_count", "eligible_count", "section_count", "published_count", "message"]].rename(
                columns={"as_of_date":"数据日", "run_id":"分析批次", "status":"状态", "model_version":"模型", "universe_count":"全量宇宙", "eligible_count":"合格", "section_count":"板块数", "published_count":"发布数", "message":"说明"}
            ),
            hide_index=True,
            width="stretch",
        )

elif page == "推荐":
    title("推荐", "按日期和批次回看每个股票板块、基金类别最多5只研究候选；不足5只不补位。")
    all_runs = recommendation_history(db)
    if all_runs.empty:
        st.markdown('<div class="empty">尚无推荐批次。请先完成“拉取信息 → 分析”。</div>', unsafe_allow_html=True)
    else:
        include_invalid = st.checkbox("包含失败、部分完成或已纠正的历史批次", value=False)
        visible_runs = all_runs if include_invalid else all_runs[all_runs.status == "complete"]
        if visible_runs.empty:
            st.warning("当前没有完整推荐批次。可勾选上方选项查看失败审计。")
            st.stop()
        dates = list(dict.fromkeys(visible_runs.as_of_date.tolist()))
        c1, c2, c3 = st.columns(3)
        chosen_date = c1.selectbox("日期", dates)
        date_runs = visible_runs[visible_runs.as_of_date == chosen_date]
        type_label = c2.selectbox("类型", ["股票", "基金"], index=0)
        asset_type = "stock" if type_label == "股票" else "fund"
        typed_runs = date_runs[date_runs.asset_type == asset_type]
        if typed_runs.empty:
            st.warning("这一天没有该类型的分析批次。")
        else:
            run_id = c3.selectbox(
                "批次",
                typed_runs.run_id,
                format_func=lambda value: f"{typed_runs.loc[typed_runs.run_id == value, 'created_at'].iloc[0]} · {value}",
            )
            run = typed_runs[typed_runs.run_id == run_id].iloc[0]
            a, b, c, d = st.columns(4)
            a.metric("批次状态", run.status)
            b.metric("全量股票" if asset_type == "stock" else "可排名基金份额", int(run.universe_count))
            c.metric("合格标的", int(run.eligible_count))
            d.metric("已发布", int(run.published_count))
            source_badge("冻结的本地推荐批次", str(run.as_of_date))
            if run.status != "complete":
                st.error("本批次不完整，因此没有把临时结果当成正式推荐。可以查看板块缺口和失败原因。")
            sections = db.query_df(
                "SELECT * FROM recommendation_sections WHERE run_id=? ORDER BY section", (run_id,)
            )
            if asset_type == "stock":
                total = int(sections.total_count.sum())
                broad = int(sections.loc[sections.section == "综合", "total_count"].sum())
                st.info(
                    f"股票板块采用来源行业优先体系 {STOCK_CLASSIFICATION_VERSION}：保留年度财务快照原始行业，"
                    f"仅把可明确识别的行业归并到10个宏观组；不是交易所官方行业码。"
                    f"本批次“综合” {broad:,}/{total:,}（{broad / total:.1%}），结果应在同组内比较。"
                )
            st.dataframe(
                sections.rename(columns={"section":"板块/类别", "total_count":"全量数量", "analyzed_count":"深度分析", "qualified_count":"达标", "published_count":"发布", "status":"状态", "message":"说明"}),
                hide_index=True,
                width="stretch",
            )
            section = st.selectbox("查看板块/类别", sections.section)
            section_state = sections[sections.section == section].iloc[0]
            items = db.query_df(
                """SELECT * FROM recommendation_scores
                WHERE run_id=? AND section=? AND recommended=1 ORDER BY rank""",
                (run_id, section),
            )
            st.subheader(f"{section} · {int(section_state.published_count)}/5")
            previous = db.query_df(
                """SELECT run_id FROM recommendation_runs
                WHERE asset_type=? AND status='complete' AND created_at<?
                ORDER BY created_at DESC LIMIT 1""",
                (asset_type, run.created_at),
            )
            if previous.empty:
                st.caption("这是该类型的首个正式批次，暂无上期变化可比较。")
            else:
                previous_items = db.query_df(
                    """SELECT code FROM recommendation_scores
                    WHERE run_id=? AND section=? AND recommended=1""",
                    (previous.iloc[0].run_id, section),
                )
                current_codes = set(items.code.astype(str))
                previous_codes = set(previous_items.code.astype(str))
                st.caption(
                    f"较上个正式批次：新进 {len(current_codes - previous_codes)} · "
                    f"保留 {len(current_codes & previous_codes)} · 退出 {len(previous_codes - current_codes)}"
                )
            if items.empty:
                st.markdown(
                    f'<div class="empty">本板块今日没有正式候选。状态：{escape(str(section_state.status))}；{escape(str(section_state.message or ""))}</div>',
                    unsafe_allow_html=True,
                )
            else:
                show = items[["rank", "code", "name", "score", "confidence", "last_value", "return_3m", "return_1y", "risk_metric", "reasons", "risks", "data_as_of"]].rename(
                    columns={"rank":"#", "code":"代码", "name":"名称", "score":"综合分", "confidence":"数据置信度", "last_value":"最新价/单位净值", "return_3m":"近3月", "return_1y":"近1年", "risk_metric":"最大回撤", "reasons":"入选依据", "risks":"主要风险", "data_as_of":"数据日"}
                )
                st.dataframe(
                    show,
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "近3月": st.column_config.NumberColumn(format="%.2%%"),
                        "近1年": st.column_config.NumberColumn(format="%.2%%"),
                        "最大回撤": st.column_config.NumberColumn(format="%.2%%"),
                    },
                )
                selected_code = st.selectbox(
                    "进入诊断",
                    items.code,
                    format_func=lambda value: f"{items.loc[items.code == value, 'name'].iloc[0]} · {value}",
                )
                if st.button("查看总览、关键指标与走势", type="primary"):
                    st.session_state["diagnosis_type"] = asset_type
                    st.session_state["diagnosis_input"] = selected_code
                    st.session_state["page"] = "诊股/诊基"
                    st.rerun()
            input_fingerprint = str(getattr(run, "input_hash", "") or "未记录")
            code_fingerprint = str(getattr(run, "code_hash", "") or "未记录")
            st.caption(
                f"模型：{run.model_version} · 输入指纹 {input_fingerprint[:12]} · 代码指纹 {code_fingerprint[:12]}。"
                "综合分是同板块研究排序，不是上涨概率，也不构成买入建议。"
            )
            with st.expander("查看本板块预筛排除审计"):
                exclusion_summary = db.query_df(
                    """SELECT stage AS 阶段,reason AS 原因,COUNT(*) AS 数量
                    FROM recommendation_exclusions WHERE run_id=? AND section=?
                    GROUP BY stage,reason ORDER BY 数量 DESC""",
                    (run_id, section),
                )
                if exclusion_summary.empty:
                    st.caption("该历史批次尚未记录逐项预筛审计。")
                else:
                    st.dataframe(exclusion_summary, hide_index=True, width="stretch")

elif page == "诊股/诊基":
    title("诊股 / 诊基", "统一查看资产总览、关键技术与风险指标、历史走势及历次推荐记录。")
    initial_type = st.session_state.get("diagnosis_type", "stock")
    type_label = st.segmented_control("资产类型", ["股票", "基金"], default="股票" if initial_type == "stock" else "基金")
    asset_type = "stock" if type_label == "股票" else "fund"
    st.session_state["diagnosis_type"] = asset_type
    if "diagnosis_input" not in st.session_state:
        st.session_state["diagnosis_input"] = "000001" if asset_type == "stock" else "161725"
    code = st.text_input("股票/基金代码", key="diagnosis_input").strip()[-6:].zfill(6)
    refresh = st.button("联网补齐最新走势", type="primary")
    trail = formal_recommendation_trail(db, asset_type, code)
    if asset_type == "stock":
        frame = load_stock(code, refresh)
        if not frame.empty:
            summary = stock_summary(frame)
            technical, indicators = stock_technical_indicators(frame)
            overview = db.query_df(
                """SELECT market,board,sector,pe,pb,market_cap,roe,revenue_growth,
                profit_growth,announcement_date FROM stock_universe_snapshots
                WHERE code=? ORDER BY fetched_at DESC LIMIT 1""",
                (code,),
            )
            st.subheader(f"{stock_name(code)} · {code}")
            source_badge("AKShare公开行情 · 前复权(qfq)", technical.trade_date.max().strftime("%Y-%m-%d"))
            if not overview.empty:
                row = overview.iloc[0]
                st.caption(
                    f"{row.market} · {row.board} · {row.sector} · 财务公告日 {row.announcement_date or '未知'}"
                    + (f" · 最近正式推荐 {trail.iloc[0].as_of_date} / {trail.iloc[0].section} 第{int(trail.iloc[0]['rank'])}名" if not trail.empty else " · 尚未进入正式推荐")
                )
            a, b, c, d, e = st.columns(5)
            a.metric("最新价", f"{summary['close']:.2f}")
            b.metric("近3月", pct(summary["return_60d"]))
            c.metric("近1年", pct(summary["return_1y"]))
            d.metric("年化波动", pct(summary["volatility"]))
            e.metric("历史最大回撤", pct(summary["max_drawdown"]))
            if not overview.empty:
                f1, f2, f3, f4, f5 = st.columns(5)
                f1.metric("PE / PB", f"{row.pe:.1f} / {row.pb:.1f}" if pd.notna(row.pb) else f"{row.pe:.1f} / 暂无")
                f2.metric("ROE", "暂无" if pd.isna(row.roe) else f"{row.roe:.1f}%")
                f3.metric("营收同比", "暂无" if pd.isna(row.revenue_growth) else f"{row.revenue_growth:.1f}%")
                f4.metric("利润同比", "暂无" if pd.isna(row.profit_growth) else f"{row.profit_growth:.1f}%")
                f5.metric("总市值", "暂无" if pd.isna(row.market_cap) else f"¥{row.market_cap / 1e8:,.0f}亿")
            st.subheader("关键技术指标")
            k1, k2, k3, k4, k5, k6 = st.columns(6)
            k1.metric("MA20 / MA60", f"{indicators['ma20']:.2f} / {indicators['ma60']:.2f}")
            k2.metric("RSI(14)", f"{indicators['rsi14']:.1f}")
            k3.metric("MACD柱", f"{indicators['macd_hist']:.3f}")
            k4.metric("ATR(14)", f"{indicators['atr14']:.3f}")
            k5.metric("量比（20日）", f"{indicators['volume_ratio']:.2f}")
            k6.metric("距52周高点", pct(indicators["distance_52w_high"]))
            period = st.segmented_control("走势区间", ["3月", "1年", "3年", "全部"], default="1年", key="stock-trend-period")
            rows = {"3月": 66, "1年": 252, "3年": 756, "全部": len(technical)}[period]
            chart = technical.tail(rows).set_index("trade_date")[["close", "ma20", "ma60", "ma120", "boll_upper", "boll_lower"]].rename(columns={"close":"前复权收盘", "ma20":"MA20", "ma60":"MA60", "ma120":"MA120", "boll_upper":"布林上轨", "boll_lower":"布林下轨"})
            st.line_chart(chart, height=420)
            left, right = st.columns(2)
            left.line_chart(technical.tail(rows).set_index("trade_date")[["macd_dif", "macd_dea", "macd_hist"]], height=260)
            right.line_chart(technical.tail(rows).set_index("trade_date")[["rsi14"]], height=260)
    else:
        try:
            frame = cached_fund_history(
                db, code, refresh=refresh, purpose="analysis", allow_network=refresh
            )
        except Exception as error:
            frame = pd.DataFrame()
            st.error(f"本地没有可用的累计净值：{error}。请点击“联网补齐最新走势”。")
        if not frame.empty:
            summary = fund_summary(frame)
            technical = fund_technical_indicators(frame)
            name_frame = db.query_df(
                """SELECT name,category,unit_nav,cumulative_nav,fee_rate,nav_date,
                return_3m,return_1y,return_2y,fund_company,manager_names,
                manager_experience_days,star_rating_count,rating_score,fund_size_cny,
                inception_date,quality_source FROM fund_universe_snapshots
                WHERE code=? ORDER BY fetched_at DESC LIMIT 1""", (code,)
            )
            unit_nav = (
                float(name_frame.iloc[0].unit_nav)
                if not name_frame.empty and pd.notna(name_frame.iloc[0].unit_nav)
                else float("nan")
            )
            unit_nav_note = "全量日快照"
            try:
                unit_frame = cached_fund_history(
                    db, code, refresh=refresh, purpose="valuation", allow_network=refresh
                )
                unit_nav = float(unit_frame.nav.iloc[-1])
                unit_nav_note = "单位净值历史"
            except Exception:
                pass
            fund_name = str(name_frame.iloc[0]["name"]) if not name_frame.empty else code
            st.subheader(f"{fund_name} · {code}")
            source_badge(str(frame.attrs.get("source", "公开基金净值")), frame.date.max().strftime("%Y-%m-%d"))
            if not name_frame.empty:
                row = name_frame.iloc[0]
                st.caption(
                    f"{row.category} · 净值日 {row.nav_date} · 页面手续费字段仅为前端申购费，不代表完整总费率"
                    + (f" · 最近正式推荐 {trail.iloc[0].as_of_date} / {trail.iloc[0].section} 第{int(trail.iloc[0]['rank'])}名" if not trail.empty else " · 尚未进入正式推荐")
                )
                q1, q2, q3, q4 = st.columns(4)
                q1.metric("基金公司", str(row.fund_company) if pd.notna(row.fund_company) else "暂无")
                q2.metric("基金经理", str(row.manager_names) if pd.notna(row.manager_names) else "暂无")
                q3.metric("公开评级均值", "暂无" if pd.isna(row.rating_score) else f"{row.rating_score:.1f}/5")
                q4.metric("估算规模", "暂无" if pd.isna(row.fund_size_cny) else f"¥{row.fund_size_cny / 1e8:,.1f}亿")
                st.caption(
                    f"成立日 {'暂无' if pd.isna(row.inception_date) or not str(row.inception_date).strip() else row.inception_date} · 经理从业 "
                    f"{'暂无' if pd.isna(row.manager_experience_days) else f'{row.manager_experience_days / 365:.1f}年'} · "
                    f"质量字段来源：{'暂无' if pd.isna(row.quality_source) or not str(row.quality_source).strip() else row.quality_source}"
                )
            a, b, c, d, e = st.columns(5)
            a.metric("单位净值（估值）", "暂无" if pd.isna(unit_nav) else f"{unit_nav:.4f}")
            b.metric("近1年总回报", pct(summary["return_1y"]))
            c.metric("年化波动", pct(summary["annualized_volatility"]))
            d.metric("最大回撤", pct(summary["max_drawdown"]))
            e.metric("Sortino", "暂无" if pd.isna(summary["sortino"]) else f"{summary['sortino']:.2f}")
            st.caption(f"单位净值来源：{unit_nav_note}。累计净值仅用于含分红回报分析，不用于份额估值。")
            if frame.attrs.get("nav_kind") != "累计净值":
                st.error("当前只有单位净值，不能准确计算含分红总回报；收益与风险指标已停用。")
            st.subheader("累计净值走势与关键指标")
            latest_technical = technical.iloc[-1]
            t1, t2, t3, t4 = st.columns(4)
            t1.metric("MA20 / MA60", f"{latest_technical.ma20:.4f} / {latest_technical.ma60:.4f}")
            t2.metric("近20日 / 60日", f"{pct(latest_technical.return_20d)} / {pct(latest_technical.return_60d)}")
            t3.metric("60日滚动波动", pct(latest_technical.rolling_volatility_60d))
            t4.metric("当前回撤", pct(latest_technical.drawdown))
            period = st.segmented_control("走势区间", ["3月", "1年", "3年", "全部"], default="1年", key="fund-trend-period")
            rows = {"3月": 66, "1年": 250, "3年": 750, "全部": len(technical)}[period]
            chart = technical.tail(rows).set_index("date")[["nav", "ma20", "ma60", "ma120"]].rename(columns={"nav":frame.attrs.get("nav_kind", "净值"), "ma20":"MA20", "ma60":"MA60", "ma120":"MA120"})
            st.line_chart(chart, height=420)
            st.line_chart(technical.tail(rows).set_index("date")[["rolling_volatility_60d", "drawdown"]], height=260)
            st.subheader("基金档案")
            st.caption("经理、规模、业绩基准、运作费用与持仓来自公开基金档案，按需联网加载；缺失字段不会补造。")
            if st.button("联网加载基金档案", key=f"diagnosis-profile-{code}"):
                with st.spinner("正在获取基金档案……"):
                    st.session_state[f"diagnosis-profile-data-{code}"] = fund_profile(code)
            profile = st.session_state.get(f"diagnosis-profile-data-{code}")
            if isinstance(profile, dict) and profile:
                for profile_section, profile_data in profile.items():
                    with st.expander(profile_section, expanded=profile_section == "基本资料"):
                        st.dataframe(profile_data, hide_index=True, width="stretch")
    st.subheader("历次推荐记录")
    if trail.empty:
        st.caption("该资产尚未进入任何正式推荐批次。")
    else:
        st.dataframe(
            trail.rename(columns={"as_of_date":"推荐日期", "run_id":"批次", "section":"板块/类别", "rank":"排名", "score":"得分", "reasons":"当时依据", "risks":"当时风险", "data_as_of":"数据日"}),
            hide_index=True,
            width="stretch",
        )

elif page == "今日":
    title("今日工作台", "先看全球环境与组合风险，再看候选和事件。")
    status = db.query_df("SELECT COUNT(*) rows, COUNT(DISTINCT code) codes, MAX(trade_date) latest FROM daily_prices").iloc[0]
    runs = db.query_df("SELECT * FROM runs ORDER BY created_at DESC LIMIT 1")
    events = upcoming_events(db, 30)
    watch = list_watchlist(db)
    portfolio = value_holdings(db, refresh=False)
    portfolio_risk = portfolio_risk_summary(portfolio)
    a, b, c, d = st.columns(4)
    a.metric("行情日期", status.latest or "未初始化")
    b.metric("组合估值", f"¥{portfolio_risk['total_cny']:,.0f}" if portfolio_risk.get("complete") else "待完整估值")
    c.metric("自选资产", len(watch))
    d.metric("30天事件", len(events))
    if not status.latest:
        st.warning("本地还没有正式行情。页面不会生成示例数据，请前往“数据管理”联网初始化。")
    st.subheader("全球市场速览")
    cached_global = []
    for name, symbol in {"标普500":"^GSPC", "恒生指数":"^HSI", "日经225":"^N225", "黄金期货":"GC=F", "长期美债ETF":"TLT", "全球股票ETF":"VT"}.items():
        try:
            frame, _ = cached_asset_history(db, symbol, period="1y")
            summary = asset_summary(frame)
            cached_global.append({"资产":name, "代码":symbol, "最新":summary["last"], "1月":summary["return_1m"], "3月":summary["return_3m"], "数据日":frame.date.max().strftime("%Y-%m-%d")})
        except Exception:
            continue
    if cached_global:
        st.dataframe(pd.DataFrame(cached_global), hide_index=True, width="stretch", column_config={"1月":st.column_config.NumberColumn(format="%.2%%"), "3月":st.column_config.NumberColumn(format="%.2%%")})
    else:
        st.caption("尚无全球市场缓存，请在“全球市场”联网刷新。")
    left, right = st.columns([1.4, 1], gap="large")
    with left:
        st.subheader("最新选股候选")
        if runs.empty:
            st.markdown('<div class="empty">尚未运行真实数据选股。完成行情初始化后才能生成候选。</div>', unsafe_allow_html=True)
        else:
            run = runs.iloc[0]
            picks = db.query_df("SELECT rank, code, name, score, return_60d, reasons FROM picks WHERE run_id=? ORDER BY rank LIMIT 8", (run.run_id,))
            source_badge("本地真实日线计算", run.as_of_date)
            show = picks.rename(columns={"rank":"#", "code":"代码", "name":"名称", "score":"评分", "return_60d":"60日", "reasons":"核心证据"})
            st.dataframe(show, hide_index=True, width="stretch", column_config={"60日": st.column_config.NumberColumn(format="%.2%%")})
    with right:
        st.subheader("即将发生")
        render_events(events, 5)
    st.subheader("自选观察")
    if watch.empty:
        st.caption("自选股为空。在股票页面点击“加入自选”。")
    else:
        st.dataframe(watch[["code", "name", "thesis", "risk_note"]].rename(columns={"code":"代码", "name":"名称", "thesis":"关注理由", "risk_note":"主要风险"}), hide_index=True, width="stretch")

elif page == "全局搜索":
    title("全局搜索", "中文名、英文名或市场代码统一查找；本地证券库与联网结果会标明来源。")
    query = st.text_input("搜索资产", placeholder="例如：腾讯、Apple、600519、TLT、黄金")
    if st.button("搜索", type="primary") and query.strip():
        with st.spinner("正在查找本地证券库与真实市场代码…"):
            st.session_state["unified-search-result"] = unified_search(db, query)
    results = st.session_state.get("unified-search-result")
    if isinstance(results, pd.DataFrame) and not results.empty:
        st.caption(f"找到 {len(results)} 项；搜索结果是证券主数据，不代表推荐。")
        st.dataframe(
            results.rename(columns={"symbol":"代码", "name":"名称", "exchange":"市场", "asset_type":"类型", "source":"来源"}),
            hide_index=True, width="stretch",
        )
        selected = st.selectbox(
            "选择资产",
            results.symbol,
            format_func=lambda value: f"{results.loc[results.symbol == value, 'name'].iloc[0]} · {value}",
        )
        selected_row = results[results.symbol == selected].iloc[0]
        a, b = st.columns(2)
        if a.button("进入价格分析", width="stretch"):
            set_research_asset(selected)
            st.rerun()
        if b.button("加入自选资产", width="stretch"):
            raw_type = str(selected_row.asset_type).lower()
            asset_type = "a_share" if selected.endswith((".SS", ".SZ")) or raw_type == "股票" and selected[:6].isdigit() else "etf" if "etf" in raw_type else "index" if "index" in raw_type or "指数" in raw_type else "bond" if "bond" in raw_type or "债" in raw_type else "commodity" if "future" in raw_type or "商品" in raw_type else "global_stock"
            save_watchlist_item(db, selected, str(selected_row["name"]), asset_type)
            st.success("已加入自选资产。")
    elif query.strip():
        st.warning("没有找到可核验的证券代码。可尝试英文名称或交易所代码。")
    else:
        st.markdown('<div class="empty">输入中文名、英文名或代码开始查找。没有查询前不展示示例搜索结果。</div>', unsafe_allow_html=True)

elif page == "全球市场":
    title("全球市场", "用主要市场指数判断环境，不用单一市场代表全世界。")
    group = st.segmented_control("市场", ["全球股指", "商品", "债券ETF", "全球ETF"], default="全球股指")
    cache_key = f"snapshot-{group}"
    if st.button("联网刷新市场", type="primary"):
        with st.spinner("正在逐项获取真实市场行情…"):
            st.session_state[cache_key] = market_snapshot(group, db)
    snapshot = st.session_state.get(cache_key)
    if isinstance(snapshot, pd.DataFrame) and not snapshot.empty:
        success = snapshot[snapshot.get("status", "ok") != "failed"].copy()
        failed = snapshot[snapshot.get("status", "ok") == "failed"].copy()
        as_of = str(success.as_of.max()) if not success.empty else "无成功数据"
        source_badge("Yahoo Finance chart + 本地缓存", as_of)
        st.caption(f"成功 {len(success)} 项 · 失败 {len(failed)} 项。失败项目不会静默消失。")
        if not failed.empty:
            with st.expander("查看失败项目"):
                st.dataframe(failed[["name", "symbol", "error"]], hide_index=True, width="stretch")
        show = success[["name", "symbol", "currency", "last", "return_1d", "return_1m", "return_3m", "return_1y", "volatility"]].rename(columns={"name":"资产", "symbol":"代码", "currency":"币种", "last":"最新", "return_1d":"1日", "return_1m":"1月", "return_3m":"3月", "return_1y":"1年", "volatility":"波动"})
        st.dataframe(show, hide_index=True, width="stretch", column_config={x:st.column_config.NumberColumn(format="%.2%%") for x in ["1日", "1月", "3月", "1年", "波动"]})
        st.bar_chart(success.set_index("name")["return_1m"], height=320)
        snapshot_actions(success, group)
    else:
        st.markdown('<div class="empty">点击“联网刷新市场”获取真实数据。未联网前不显示数值。</div>', unsafe_allow_html=True)

elif page == "半导体多空战况":
    title("半导体实时战况", "海力士ADR · 美光 · 闪迪 · 费城半导体，一眼看清美股盘中多空力量。")
    symbol_signature = tuple(config["symbol"] for config in SEMICONDUCTOR_MARKETS.values())
    if st.session_state.get("semiconductor_symbol_signature") != symbol_signature:
        st.session_state.pop("semiconductor_payload", None)
        st.session_state["semiconductor_symbol_signature"] = symbol_signature
        st.session_state["semiconductor_force_refresh"] = True
    if "semiconductor_auto_refresh" not in st.session_state:
        st.session_state["semiconductor_auto_refresh"] = True
    if "semiconductor_payload" not in st.session_state:
        st.session_state["semiconductor_force_refresh"] = True
    c1, c2, c3 = st.columns([1, 1, 3])
    c1.toggle("实时刷新", key="semiconductor_auto_refresh", help="每 15 秒重新拉取一次一分钟行情")
    if c2.button("立即刷新", width="stretch"):
        st.session_state["semiconductor_force_refresh"] = True
    c3.caption("1分钟行情 · VWAP / EMA / MACD / RSI / 量价压力")
    render_semiconductor_battle()

elif page == "多层市场雷达":
    title("多层市场雷达", "从区域大盘下钻到板块、基金和个股；每个数字都保留来源与口径。")
    if "radar_auto_refresh" not in st.session_state:
        st.session_state["radar_auto_refresh"] = True
    view = st.segmented_control(
        "观察粒度", ["大盘", "板块", "基金 / 个股", "自定义"],
        default="大盘", key="radar_view",
    )
    if view != "自定义":
        region = st.segmented_control("市场", list(REGIONS), default="美国", key="radar_region")
    else:
        region = "跨市场"
    c1, c2, c3 = st.columns([1, 1, 3])
    c1.toggle("实时刷新", key="radar_auto_refresh", help="每20秒拉取当前所选层级的一分钟行情")
    if c2.button("立即刷新", key="radar-refresh", width="stretch"):
        st.session_state["radar_force_refresh"] = True
    c3.caption("只请求当前选择 · 1分钟行情 · 免费源可能延迟")

    universe: dict[str, str] = {}
    if view == "大盘":
        universe = dict(INDEX_UNIVERSES[region])
    elif view == "板块":
        universe = dict(SECTOR_UNIVERSES[region])
        st.info("板块使用当地上市的行业ETF作为可交易代理；资金字段为量价成交额代理，不是交易所净流入。")
    elif view == "基金 / 个股":
        choices = INSTRUMENT_UNIVERSES[region]
        selected_name = st.selectbox(
            "选择基金或个股", list(choices), key="radar_instrument",
            format_func=lambda name: f"{name} · {choices[name]}",
        )
        universe = {selected_name: choices[selected_name]}
    else:
        custom_text = st.text_input(
            "自定义市场代码（最多12个）",
            value="SPY, QQQ, SKHY, MU",
            key="radar_custom_symbols",
            help="支持 Yahoo Finance 市场代码，例如 000300.SS、7203.T、ASML.AS、GC=F。",
        )
        try:
            symbols = parse_custom_symbols(custom_text)
            universe = {symbol: symbol for symbol in symbols}
        except ValueError as error:
            st.error(str(error))
    if universe:
        render_market_radar(str(view), region, universe)
    else:
        st.info("输入至少一个有效市场代码后开始监测。")

elif page == "A股选股":
    title("A股选股", "先硬性剔除无有效PE、PE超限、120日回撤低于-40%或20日年化波动高于80%的标的，再做横截面排序。")
    runs = db.query_df("SELECT * FROM runs WHERE status='success' ORDER BY created_at DESC LIMIT 30")
    if runs.empty:
        st.warning("尚无选股结果。请先在“数据管理”完成联网更新。")
    else:
        run_id = st.selectbox("数据批次", runs.run_id, format_func=lambda value: f"{runs.loc[runs.run_id == value, 'as_of_date'].iloc[0]} 更新")
        picks = db.query_df("SELECT * FROM picks WHERE run_id=? ORDER BY rank", (run_id,))
        source_badge("本地真实日线与估值快照计算", runs.loc[runs.run_id == run_id, "as_of_date"].iloc[0])
        f1, f2, f3 = st.columns(3)
        min_score = f1.slider("最低综合分", 0, 100, 50)
        max_pe = f2.number_input("PE 上限（0=不限）", min_value=0.0, value=60.0)
        max_drawdown = f3.slider("可接受最大回撤", 10, 80, 40) / -100
        filtered = picks[(picks.score >= min_score) & (picks.max_drawdown_120d >= max_drawdown)]
        if max_pe:
            filtered = filtered[filtered.pe.notna() & (filtered.pe <= max_pe)]
        compact = filtered[["rank", "code", "name", "score", "return_60d", "max_drawdown_120d", "pe", "reasons"]].rename(columns={"rank":"#", "code":"代码", "name":"名称", "score":"综合分", "return_60d":"60日", "max_drawdown_120d":"回撤", "pe":"PE", "reasons":"为什么入选"})
        st.dataframe(compact, hide_index=True, width="stretch", column_config={"60日":st.column_config.NumberColumn(format="%.2%%"), "回撤":st.column_config.NumberColumn(format="%.2%%")})
        if not filtered.empty:
            selected = st.selectbox("继续研究", filtered.code, format_func=lambda x: f"{x} · {filtered.loc[filtered.code == x, 'name'].iloc[0]}")
            x, y = st.columns(2)
            if x.button("设为当前股票", width="stretch"):
                suffix = ".SS" if selected.startswith(("60", "68")) else ".SZ"
                st.session_state["active_stock"] = selected
                set_research_asset(selected + suffix)
                st.rerun()
            if y.button("加入自选股", width="stretch"):
                name = filtered.loc[filtered.code == selected, "name"].iloc[0]
                save_watchlist_item(db, selected, name, "a_share")
                st.success("已加入自选股。")

elif page == "全球选股":
    title("全球股票筛选", "在透明的跨市场流动性研究池中比较估值、盈利/现金流质量、动量与回撤；得分是横截面排序，不是上涨概率。")
    st.caption(f"固定研究池 {len(GLOBAL_EQUITY_UNIVERSE)} 只，覆盖美国、香港、日本、欧洲、英国和澳大利亚。金融股因现金流报表结构不同被排除；评分加入行业与地区内排序及绝对质量门槛。当前成分仍有幸存者偏差，不可直接用于历史回测。")
    if st.button("联网运行全球筛选", type="primary"):
        try:
            with exclusive_job(db, ROOT / "data" / ".writer.lock", "global_equity_screen") as job:
                with st.spinner("正在并行获取真实复权行情和公开基本面…"):
                    ranked, failures = screen_global_equities(db, refresh=True)
                job["succeeded"] = len(ranked)
                job["failed"] = len(failures)
                job["message"] = f"universe={len(GLOBAL_EQUITY_UNIVERSE)} eligible={len(ranked)}"
                st.session_state["global-screen"] = ranked
                st.session_state["global-screen-failures"] = failures
        except Exception as error:
            st.error(f"筛选任务失败：{error}")
    ranked = st.session_state.get("global-screen")
    failures = st.session_state.get("global-screen-failures", [])
    if isinstance(ranked, pd.DataFrame) and not ranked.empty:
        source_badge("Yahoo Finance 复权行情 + fundamentals timeseries", str(ranked.as_of.max()))
        st.caption(f"有效可比 {len(ranked)} 只 · 失败 {len(failures)} 只。缺少任一必要指标的证券不参与排序。")
        if failures:
            with st.expander("查看失败或不可比标的"):
                st.write(failures)
        show = ranked[["symbol", "name", "region", "sector", "score", "pe", "roa_proxy", "fcf_margin_proxy", "return_1y", "max_drawdown", "evidence"]].rename(columns={"symbol":"代码", "name":"名称", "region":"地区", "sector":"行业组", "score":"综合分", "pe":"PE", "roa_proxy":"ROA代理", "fcf_margin_proxy":"FCF利润率代理", "return_1y":"1年收益", "max_drawdown":"区间最大回撤", "evidence":"证据"})
        st.dataframe(show, hide_index=True, width="stretch", column_config={column:st.column_config.NumberColumn(format="%.2%%") for column in ["ROA代理", "FCF利润率代理", "1年收益", "区间最大回撤"]})
        selected = st.selectbox("继续研究", ranked.symbol, format_func=lambda value: f"{ranked.loc[ranked.symbol == value, 'name'].iloc[0]} · {value}")
        a, b = st.columns(2)
        if a.button("进入价格分析", width="stretch"):
            set_research_asset(selected)
            st.rerun()
        if b.button("加入自选", width="stretch"):
            row = ranked[ranked.symbol == selected].iloc[0]
            save_watchlist_item(db, selected, row["name"], "global_stock")
            st.success("已加入自选资产。")
        st.warning("评分没有行业中性、交易成本或样本外验证；财务口径受市场会计准则和披露频率影响。请进入基本面页并与公司公告复核。")
    else:
        st.markdown('<div class="empty">点击按钮后才会联网运行；没有结果前不展示示例排名。</div>', unsafe_allow_html=True)

elif page == "自选资产":
    title("自选资产", "股票、基金、ETF、债券和商品共用一张观察清单。")
    watch = list_watchlist(db)
    if watch.empty:
        st.markdown('<div class="empty">还没有自选标的。可在选股结果或股票页面加入。</div>', unsafe_allow_html=True)
    else:
        asset_label = {"stock":"股票", "fund":"基金"}
        display = watch.copy()
        display["asset_type"] = display.asset_type.map(ASSET_TYPE_LABELS).fillna(display.asset_type)
        st.dataframe(display[["asset_type", "code", "name", "thesis", "risk_note", "updated_at"]].rename(columns={"asset_type":"类型", "code":"代码", "name":"名称", "thesis":"关注理由", "risk_note":"主要风险", "updated_at":"更新于"}), hide_index=True, width="stretch")
        option = st.selectbox("编辑标的", range(len(watch)), format_func=lambda i: f"{watch.iloc[i]['code']} · {watch.iloc[i]['name']}")
        row = watch.iloc[option]
        with st.form("edit-watch"):
            thesis = st.text_area("关注理由", row.thesis or "", placeholder="什么证据让它值得持续观察？")
            risk_note = st.text_area("推翻条件 / 主要风险", row.risk_note or "", placeholder="什么发生时应重新评估？")
            if st.form_submit_button("保存研究卡", type="primary"):
                save_watchlist_item(db, row.code, row["name"], row.asset_type, thesis, risk_note)
                st.success("已保存。")
                st.rerun()
        a, b, c = st.columns(3)
        if a.button("进入研究", width="stretch"):
            set_research_asset(str(row.code))
            st.rerun()
        if b.button("带入持仓", width="stretch"):
            st.session_state["pending_holding_symbol"] = str(row.code)
            st.session_state["pending_holding_name"] = str(row["name"])
            pending_type = "a_share" if str(row.asset_type) == "stock" and str(row.code).isdigit() else str(row.asset_type)
            st.session_state["pending_holding_type"] = pending_type
            st.session_state["page"] = "持仓"
            st.rerun()
        if c.button("移出自选", width="stretch"):
            remove_watchlist_item(db, row.code, row.asset_type)
            st.rerun()

elif page == "投资约束":
    title("投资约束", "先记录期限、流动性和最大可承受回撤；工具不会据此自动下单。")
    profile = get_investor_profile(db) or {}
    with st.form("profile-form"):
        horizon = st.slider("投资期限（年）", 1, 30, int(profile.get("horizon_years", 5)))
        max_drawdown = st.slider("最大可承受阶段回撤", 5, 80, int(float(profile.get("max_drawdown_pct", 0.25)) * 100))
        liquidity = st.slider("应急流动性储备（月）", 0, 36, int(profile.get("liquidity_months", 6)))
        base_currency = st.selectbox("组合基准币种", ["CNY"], help="当前组合估值只支持人民币基准；其他基准币种尚未开放。")
        objective = st.selectbox("主要目标", ["长期增值", "稳健增值", "现金流", "资本保全", "其他"], index=0)
        if st.form_submit_button("保存约束", type="primary"):
            save_investor_profile(db, horizon, max_drawdown / 100, liquidity, base_currency, objective)
            st.success("已保存到本机。")
    st.info("这是研究边界记录，不是完整适当性评估。任何资产配置仍需结合收入稳定性、负债、税务和具体用途。")

elif page == "交易记录":
    title("交易记录", "记录买卖、分红、费用和成交日汇率；这是审计账本，不会自动下单。")
    with st.form("transaction-form"):
        c1, c2, c3 = st.columns(3)
        trade_date = c1.date_input("交易日期", value=date.today())
        symbol = c2.text_input("市场代码", placeholder="AAPL / 0700.HK / 600519.SS")
        asset_type = c3.selectbox("资产类型", [key for key in ASSET_TYPE_LABELS if key not in {"commodity", "stock"}], format_func=lambda value: ASSET_TYPE_LABELS[value])
        c4, c5, c6 = st.columns(3)
        side = c4.selectbox("方向", ["buy", "sell", "dividend", "fee"], format_func=lambda value: {"buy":"买入", "sell":"卖出", "dividend":"分红/利息", "fee":"单独费用"}[value])
        quantity = c5.number_input("数量", min_value=0.0, value=1.0)
        price = c6.number_input("成交价/每单位金额", min_value=0.0, value=1.0)
        c7, c8, c9 = st.columns(3)
        fees = c7.number_input("费用", min_value=0.0, value=0.0)
        currency = c8.selectbox("成交币种", ["CNY", "USD", "HKD", "JPY", "EUR", "GBP", "AUD", "CAD", "CHF"])
        fx_to_cny = c9.number_input("成交日兑人民币汇率", min_value=0.0, value=1.0, help="1单位成交币种折合多少人民币；必须按成交日真实汇率填写。")
        account = st.text_input("账户（可选，用于分账）")
        note = st.text_input("备注（可选）")
        if st.form_submit_button("保存交易", type="primary"):
            if not symbol.strip():
                st.error("请填写真实市场代码。")
            elif quantity == 0 and side in {"buy", "sell"}:
                st.error("买卖数量必须大于 0。")
            else:
                add_transaction(db, symbol, asset_type, trade_date.isoformat(), side, quantity, price, fees, currency, fx_to_cny, note, account)
                st.success("交易已写入本机账本。")
                st.rerun()
    transactions = list_transactions(db)
    if transactions.empty:
        st.markdown('<div class="empty">尚无交易记录。系统不会创建示例流水。</div>', unsafe_allow_html=True)
    else:
        show = transactions.copy()
        show["asset_type"] = show.asset_type.map(ASSET_TYPE_LABELS).fillna(show.asset_type)
        show["side"] = show.side.map({"buy":"买入", "sell":"卖出", "dividend":"分红/利息", "fee":"费用"}).fillna(show.side)
        st.dataframe(show[["transaction_id", "trade_date", "account", "symbol", "asset_type", "side", "quantity", "price", "fees", "currency", "fx_to_cny", "note"]].rename(columns={"transaction_id":"ID", "trade_date":"日期", "account":"账户", "symbol":"代码", "asset_type":"类型", "side":"方向", "quantity":"数量", "price":"成交价/金额", "fees":"费用", "currency":"币种", "fx_to_cny":"成交日汇率", "note":"备注"}), hide_index=True, width="stretch")
        ledger = transaction_ledger_summary(db)
        st.subheader("账本汇总（人民币平均成本法）")
        st.dataframe(ledger.rename(columns={"symbol":"代码", "account":"账户", "currency":"成交币种", "asset_type":"类型", "net_quantity":"账本净数量", "cost_basis_cny":"剩余成本基础", "realized_pnl_cny":"已实现损益", "income_cny":"分红利息净收入", "quality_status":"质量状态", "average_cost_cny":"人民币平均成本"}), hide_index=True, width="stretch")
        if (ledger.quality_status != "ok").any():
            st.warning("部分账本缺少成交日汇率或卖出数量超过已记录买入，因此相关损益被拒绝计算。")
        holdings = list_holdings(db)
        if not holdings.empty:
            recorded = holdings.groupby(["symbol", "account"], as_index=False).quantity.sum().rename(columns={"quantity":"持仓页数量"})
            reconciliation = ledger.groupby(["symbol", "account"], as_index=False).net_quantity.sum().merge(recorded, on=["symbol", "account"], how="outer").fillna(0)
            reconciliation["差异"] = reconciliation["持仓页数量"] - reconciliation.net_quantity
            st.subheader("持仓对账")
            st.dataframe(reconciliation.rename(columns={"symbol":"代码", "account":"账户", "net_quantity":"账本数量"}), hide_index=True, width="stretch")
        target_transaction = st.selectbox("选择需纠错删除的流水", transactions.transaction_id, format_func=lambda value: f"#{value} · {transactions.loc[transactions.transaction_id == value, 'trade_date'].iloc[0]} · {transactions.loc[transactions.transaction_id == value, 'symbol'].iloc[0]}")
        if st.button("确认删除所选流水"):
            delete_transaction(db, int(target_transaction))
            st.success("所选流水已删除，账本已重算。")
            st.rerun()
        st.info("交易账本保留成交日汇率并计算已实现损益；持仓仍由“持仓”页确认，避免不完整旧流水自动改写真实数量。")

elif page == "持仓":
    title("持仓", "手工录入真实持仓；价格联网更新，成本与数量只保存在本机。")
    if "pending_holding_symbol" in st.session_state:
        st.session_state["holding_symbol_input"] = st.session_state.pop("pending_holding_symbol")
        st.session_state["holding_name_input"] = st.session_state.pop("pending_holding_name", "")
        pending_type = st.session_state.pop("pending_holding_type", "global_stock")
        st.session_state["holding_type_input"] = pending_type if pending_type not in {"commodity", "stock"} else "global_stock"
    with st.form("holding-form"):
        c1, c2, c3 = st.columns(3)
        symbol = c1.text_input("市场代码", placeholder="AAPL / 0700.HK / TLT", key="holding_symbol_input")
        holding_name = c2.text_input("名称", key="holding_name_input")
        holding_types = [key for key in ASSET_TYPE_LABELS if key not in {"commodity", "stock"}]
        if st.session_state.get("holding_type_input") not in holding_types:
            st.session_state["holding_type_input"] = "global_stock"
        asset_type = c3.selectbox("资产类型", holding_types, format_func=lambda value: ASSET_TYPE_LABELS[value], key="holding_type_input")
        c4, c5, c6 = st.columns(3)
        quantity = c4.number_input("数量", min_value=0.000001, value=1.0)
        cost = c5.number_input("单位成本", min_value=0.0, value=1.0)
        currency = c6.selectbox("成本币种", ["CNY", "USD", "HKD", "JPY", "EUR", "GBP", "AUD", "CAD", "CHF"])
        account = st.text_input("账户（可选）")
        note = st.text_input("备注（可选）")
        if st.form_submit_button("添加持仓", type="primary"):
            if not symbol.strip():
                st.error("请填写真实市场代码。")
            else:
                add_holding(db, symbol, holding_name, asset_type, quantity, cost, currency, account, note, 1.0)
                st.success("已保存到本机。")
                st.rerun()
    st.caption("连续期货仅用于研究代理，不允许作为普通现货持仓估值；黄金敞口可录入有明确份额净值的黄金 ETF。")
    holdings = list_holdings(db)
    if holdings.empty:
        st.markdown('<div class="empty">尚无持仓。系统不会创建示例组合。</div>', unsafe_allow_html=True)
    else:
        holding_display = holdings.copy()
        holding_display["asset_type"] = holding_display.asset_type.map(ASSET_TYPE_LABELS).fillna(holding_display.asset_type)
        st.dataframe(holding_display[["holding_id", "symbol", "name", "asset_type", "quantity", "cost_price", "currency", "account", "contract_multiplier"]].rename(columns={"holding_id":"ID", "symbol":"代码", "name":"名称", "asset_type":"类型", "quantity":"数量", "cost_price":"成本", "currency":"币种", "account":"账户", "contract_multiplier":"合约乘数"}), hide_index=True, width="stretch")
        holding_id = st.selectbox("删除持仓", holdings.holding_id, format_func=lambda x: f"{x} · {holdings.loc[holdings.holding_id == x, 'symbol'].iloc[0]}")
        if st.button("确认删除所选持仓"):
            delete_holding(db, int(holding_id))
            st.rerun()

elif page == "目标配置":
    title("目标配置", "把长期目标权重与当前真实估值对照；偏离只用于复核，不自动生成交易指令。")
    categories = ["a_share", "global_stock", "fund", "etf", "bond", "cash"]
    existing = db.query_df("SELECT asset_type, target_weight FROM target_allocations")
    current_targets = dict(zip(existing.asset_type, existing.target_weight)) if not existing.empty else {}
    with st.form("target-form"):
        st.caption("目标权重合计必须为 100%。")
        inputs = {}
        columns = st.columns(3)
        for index, category in enumerate(categories):
            inputs[category] = columns[index % 3].number_input(ASSET_TYPE_LABELS[category], min_value=0.0, max_value=100.0, value=float(current_targets.get(category, 0) * 100), step=1.0, key=f"target-{category}")
        if st.form_submit_button("保存目标", type="primary"):
            total = sum(inputs.values())
            if abs(total - 100) > 0.1:
                st.error(f"当前合计 {total:.1f}%，请调整为 100%。")
            else:
                save_target_allocations(db, {key: value / 100 for key, value in inputs.items()})
                st.success("目标配置已保存。")
                st.rerun()
    valued = value_holdings(db, refresh=False)
    drift = allocation_drift(db, valued)
    if drift.empty:
        st.markdown('<div class="empty">保存目标且完成全部持仓估值后，这里会显示当前权重与偏离。</div>', unsafe_allow_html=True)
    else:
        drift["类型"] = drift.asset_type.map(ASSET_TYPE_LABELS).fillna(drift.asset_type)
        st.dataframe(drift[["类型", "target_weight", "current_weight", "drift"]].rename(columns={"target_weight":"目标权重", "current_weight":"当前权重", "drift":"偏离"}), hide_index=True, width="stretch", column_config={column:st.column_config.NumberColumn(format="%.2%%") for column in ["目标权重", "当前权重", "偏离"]})
        st.bar_chart(drift.set_index("类型")[["target_weight", "current_weight"]], height=360)
        st.caption("偏离 = 当前权重 − 目标权重。再平衡前还需考虑税费、交易成本、现金需求和你的投资约束。")

elif page == "资产配置":
    title("资产配置", "按最新真实价格和实时汇率折算人民币；任一价格或汇率缺失时不伪造组合总值。")
    refresh = st.button("联网刷新组合", type="primary")
    with st.spinner("正在读取持仓价格与汇率…"):
        valued = value_holdings(db, refresh=refresh)
    if valued.empty:
        st.markdown('<div class="empty">没有持仓。请先在“持仓”菜单录入。</div>', unsafe_allow_html=True)
    else:
        valued["asset_type_label"] = valued.asset_type.map(ASSET_TYPE_LABELS).fillna(valued.asset_type)
        show = valued[["symbol", "name", "asset_type_label", "quantity", "latest_price", "quote_currency", "price_date", "market_value_cny", "weight", "pnl_pct"]].rename(columns={"symbol":"代码", "name":"名称", "asset_type_label":"类型", "quantity":"数量", "latest_price":"最新价", "quote_currency":"计价币", "price_date":"价格日期", "market_value_cny":"人民币市值", "weight":"权重", "pnl_pct":"持仓收益"})
        mismatched = valued[valued.currency_mismatch]
        if not mismatched.empty:
            st.warning(f"{len(mismatched)} 项持仓的录入成本币种与市场计价币不同，因此不显示这些持仓的收益率；市值仍按市场币种折算。")
        st.dataframe(show, hide_index=True, width="stretch", column_config={"权重":st.column_config.NumberColumn(format="%.2%%"), "持仓收益":st.column_config.NumberColumn(format="%.2%%")})
        risk = portfolio_risk_summary(valued)
        if risk.get("complete"):
            st.metric("组合估值（人民币）", f"¥{risk['total_cny']:,.2f}")
            left, right = st.columns(2)
            left.subheader("资产类别")
            left.bar_chart(risk["asset_exposure"])
            right.subheader("计价币种")
            right.bar_chart(risk["currency_exposure"])
        else:
            st.warning("部分持仓没有取得真实价格或汇率，因此不显示组合总值和配置比例。")

elif page == "集中度风险":
    title("集中度风险", "集中度描述组合结构，不预测市场涨跌。")
    valued = value_holdings(db, refresh=False)
    risk = portfolio_risk_summary(valued)
    if not risk.get("complete"):
        st.warning("需要所有持仓都能取得真实价格和汇率，才能计算集中度。")
    else:
        a, b, c = st.columns(3)
        a.metric("最大单一持仓", pct(risk["largest_weight"]))
        b.metric("有效持仓数", f"{risk['effective_count']:.1f}")
        c.metric("实际持仓数", len(valued))
        st.bar_chart(valued.set_index("symbol")["weight"].sort_values(ascending=False), height=350)
        if risk["largest_weight"] > 0.30:
            st.warning("最大单一持仓超过 30%。这是集中度提示，不是自动减仓指令。")
        else:
            st.info("单一持仓集中度未超过 30%；仍需结合资产相关性、投资期限和流动性评估。")

elif page == "资产相关性":
    title("资产相关性", "使用近两年真实复权行情并统一折算人民币，观察共同波动；历史相关性会变化。")
    with st.spinner("正在读取历史价格和汇率…"):
        returns = holding_return_matrix(db)
    if returns.shape[1] < 2:
        st.warning("至少需要两项可取得真实历史价格与汇率的非现金持仓。")
    else:
        correlation = returns.tail(252).corr()
        st.dataframe(correlation.style.format("{:.2f}").background_gradient(cmap="RdYlGn", vmin=-1, vmax=1), width="stretch")
        st.caption(f"共同有效观测：{len(returns.tail(252))} 个交易日。相关性不是稳定常数，不代表极端行情下仍然有效。")

elif page == "压力情景":
    title("压力情景", "把你设定的价格冲击应用到当前持仓。结果是机械估算，不是市场预测。")
    valued = value_holdings(db, refresh=False)
    with st.form("stress-form"):
        st.caption("填写各资产类别的假设涨跌幅")
        c1, c2, c3 = st.columns(3)
        stock_shock = c1.slider("股票 / ETF", -60, 30, -20) / 100
        bond_shock = c2.slider("债券 / 债券ETF", -30, 20, -8) / 100
        commodity_shock = c3.slider("商品", -50, 50, -15) / 100
        run_stress = st.form_submit_button("运行假设情景", type="primary")
    if run_stress:
        shocks = {"global_stock":stock_shock, "a_share":stock_shock, "fund":stock_shock, "etf":stock_shock, "bond":bond_shock, "commodity":commodity_shock, "cash":0.0}
        result = stress_portfolio(valued, shocks)
        if not result.get("complete"):
            st.error("部分持仓无法取得真实市值，拒绝计算压力结果。")
        else:
            a, b = st.columns(2)
            a.metric("假设市值变化", f"¥{result['change_cny']:,.2f}")
            b.metric("假设组合变化", pct(result["change_pct"]))
            details = result["details"][["symbol", "name", "asset_type", "market_value_cny", "assumed_shock", "estimated_change_cny"]].rename(columns={"symbol":"代码", "name":"名称", "asset_type":"类型", "market_value_cny":"当前市值", "assumed_shock":"假设冲击", "estimated_change_cny":"估算变化"})
            st.dataframe(details, hide_index=True, width="stretch", column_config={"假设冲击":st.column_config.NumberColumn(format="%.2%%")})
            st.warning("未建模波动率变化、相关性失效、流动性折价、保证金、税费或非线性衍生品风险。")

elif page == "全球证券分析":
    title("全球证券分析", "输入真实市场代码，统一分析全球股票、ETF、指数、债券ETF和商品。")
    examples = {"标普500":"^GSPC", "苹果":"AAPL", "腾讯":"0700.HK", "丰田":"7203.T", "SAP德国":"SAP.DE", "黄金期货连续合约":"GC=F", "长期美债ETF":"TLT", "全球股票ETF":"VT"}
    preset = st.selectbox("常用示例", examples.keys())
    search_query = st.text_input("按名称或代码搜索", placeholder="例如 Apple、腾讯、TLT")
    if st.button("搜索证券") and search_query.strip():
        try:
            st.session_state["asset-search"] = search_assets(search_query)
        except Exception as error:
            st.error(f"搜索失败：{error}")
    search_result = st.session_state.get("asset-search")
    if isinstance(search_result, pd.DataFrame) and not search_result.empty:
        selected_search = st.selectbox("搜索结果", search_result.symbol, format_func=lambda value: f"{search_result.loc[search_result.symbol == value, 'name'].iloc[0]} · {value} · {search_result.loc[search_result.symbol == value, 'exchange'].iloc[0]}")
        if st.button("使用搜索结果"):
            st.session_state["active_symbol"] = selected_search
            st.rerun()
    symbol = st.text_input("市场代码", value=st.session_state.get("active_symbol", examples[preset]), help="A股如 600519.SS；港股如 0700.HK；美股如 AAPL；日股如 7203.T；黄金期货 GC=F")
    analyze = st.button("联网分析", type="primary")
    try:
        frame, data_source = cached_asset_history(db, symbol, refresh=analyze, period="5y")
    except Exception as error:
        frame, data_source = pd.DataFrame(), ""
        if analyze:
            st.error(f"未取得真实行情：{error}")
    if not frame.empty:
        st.session_state["active_symbol"] = symbol.upper()
        summary = asset_summary(frame)
        source_badge(data_source or "本地真实缓存", frame.date.max().strftime("%Y-%m-%d"))
        if frame.attrs.get("cache_status") == "stale":
            st.warning("本次联网刷新失败，当前展示的是上次成功缓存，不是最新数据。")
        meta = db.query_df("SELECT currency, exchange_timezone, instrument_type, fetched_at FROM asset_metadata WHERE symbol=?", (symbol.upper(),))
        if not meta.empty:
            row = meta.iloc[0]
            st.caption(f"币种 {row.currency or '未知'} · 市场时区 {row.exchange_timezone or '未知'} · 类型 {row.instrument_type or '未知'} · 抓取于 {row.fetched_at}")
        a, b, c, d, e = st.columns(5)
        a.metric("最新", f"{summary['last']:.2f}")
        b.metric("1月", pct(summary["return_1m"]))
        c.metric("3月", pct(summary["return_3m"]))
        d.metric("1年", pct(summary["return_1y"]))
        e.metric("最大回撤", pct(summary["max_drawdown"]))
        st.line_chart(frame.set_index("date")[["close", "ma20", "ma60"]], height=430)
        st.area_chart(frame.set_index("date")["drawdown"], height=240)
        asset_type = st.selectbox("加入自选时归类", ["global_stock", "etf", "bond", "commodity", "index"])
        if st.button("加入自选资产"):
            save_watchlist_item(db, symbol.upper(), symbol.upper(), asset_type)
            st.success("已加入。")
    else:
        st.markdown('<div class="empty">输入代码并联网分析。获取失败时不会显示替代价格。</div>', unsafe_allow_html=True)

elif page == "全球基本面":
    title("全球基本面", "规范化展示公开财务序列；缺失字段不估算、不补造。")
    symbol = st.text_input("证券代码", value=st.session_state.get("active_symbol", "AAPL"))
    source_badge("Yahoo Finance fundamentals timeseries")
    if st.button("联网获取基本面", type="primary"):
        try:
            with st.spinner("正在查询公开财务与估值时间序列…"):
                st.session_state[f"fundamental-{symbol}"] = cached_fundamentals(db, symbol, refresh=True)
                cached_asset_history(db, symbol, period="1mo")
        except Exception as error:
            st.error(f"基本面获取失败：{error}")
    fundamentals = st.session_state.get(f"fundamental-{symbol}")
    if isinstance(fundamentals, pd.DataFrame) and not fundamentals.empty:
        labels = {
            "trailingMarketCap":"市值", "trailingPeRatio":"滚动市盈率",
            "trailingEnterprisesValueEBITDARatio":"EV/EBITDA", "annualTotalRevenue":"年度营收",
            "annualNetIncome":"年度净利润", "annualFreeCashFlow":"年度自由现金流",
            "annualTotalAssets":"年度总资产", "annualStockholdersEquity":"年度股东权益",
        }
        show = fundamentals.copy()
        raw_field = show.field.copy()
        numeric = pd.to_numeric(show.value, errors="coerce")
        monetary = raw_field.str.startswith("annual") | raw_field.eq("trailingMarketCap")
        ratio = raw_field.isin(["trailingPeRatio", "trailingEnterprisesValueEBITDARatio"])
        show["数值展示"] = numeric.map(lambda value: "缺失" if pd.isna(value) else f"{value:,.2f}")
        show.loc[monetary, "数值展示"] = [f"{value / 1e9:,.2f} 十亿" if pd.notna(value) else "缺失" for value in numeric[monetary]]
        show.loc[ratio, "数值展示"] = [f"{value:.2f}×" if pd.notna(value) else "缺失" for value in numeric[ratio]]
        latest = lambda field: pd.to_numeric(fundamentals.loc[fundamentals.field == field, "value"], errors="coerce").dropna().iloc[-1] if not pd.to_numeric(fundamentals.loc[fundamentals.field == field, "value"], errors="coerce").dropna().empty else float("nan")
        pe, revenue, income, fcf, assets = latest("trailingPeRatio"), latest("annualTotalRevenue"), latest("annualNetIncome"), latest("annualFreeCashFlow"), latest("annualTotalAssets")
        m1, m2, m3 = st.columns(3)
        m1.metric("滚动 PE", "暂无" if pd.isna(pe) else f"{pe:.2f}×")
        m2.metric("ROA 代理", "暂无" if pd.isna(income) or pd.isna(assets) or not assets else pct(income / assets))
        m3.metric("FCF 利润率代理", "暂无" if pd.isna(fcf) or pd.isna(revenue) or not revenue else pct(fcf / revenue))
        show["field"] = show.field.map(labels).fillna(show.field)
        st.dataframe(show[["date", "field", "数值展示", "currency"]].rename(columns={"date":"报告/数据日", "field":"指标", "currency":"报告币种"}), hide_index=True, width="stretch")
        meta = db.query_df("SELECT currency,exchange_name,fetched_at FROM asset_metadata WHERE symbol=?", (symbol.upper(),))
        if not meta.empty:
            st.caption(f"市场报价币种参考：{meta.iloc[0].currency or '未知'} · 交易所 {meta.iloc[0].exchange_name or '未知'}。报价币种不能替代公司财务报告币种。")
        st.caption("ROA/FCF 利润率为最新公开年度字段的简单代理。不同披露期、会计准则、行业结构和货币不可未经调整直接横向比较。")
    else:
        st.markdown('<div class="empty">点击按钮联网获取。接口没有返回的指标会保持缺失。</div>', unsafe_allow_html=True)

elif page == "A股财务":
    title("财务质量", "直接读取公开财务指标；关键值必须与公司定期报告复核。")
    code = a_share_selector("financials")
    st.subheader(f"{stock_name(code)} · {code}")
    source_badge("AKShare 公开财务接口")
    if st.button("联网加载财务数据", type="primary"):
        with st.spinner("正在联网查询…"):
            frame = stock_financials(code)
        if frame.empty:
            st.error("没有取得财务数据。本页不会补造指标。")
        else:
            st.session_state[f"financials-{code}"] = frame
    financials = st.session_state.get(f"financials-{code}")
    if isinstance(financials, pd.DataFrame) and not financials.empty:
        preferred = [column for column in ["日期", "净资产收益率(%)", "加权净资产收益率(%)", "销售毛利率(%)", "主营业务利润率(%)", "资产负债率(%)", "每股经营性现金流(元)"] if column in financials.columns]
        st.dataframe(financials[preferred] if preferred else financials, hide_index=True, width="stretch")
        with st.expander("查看全部原始字段"):
            st.dataframe(financials, hide_index=True, width="stretch")
    else:
        st.markdown('<div class="empty">点击上方按钮获取真实财务数据。</div>', unsafe_allow_html=True)

elif page == "研究笔记":
    title("研究笔记", "把判断和证据留痕，避免只记得结果、不记得当时为什么。")
    code = a_share_selector("notes")
    st.subheader(f"{stock_name(code)} · {code}")
    with st.form("new-note"):
        note = st.text_area("新笔记", placeholder="记录事实、推论、待核验项；不要只写‘看好’。")
        if st.form_submit_button("保存笔记", type="primary"):
            add_note(db, code, note)
            st.success("已保存到本地。")
            st.rerun()
    notes = list_notes(db, code)
    if notes.empty:
        st.caption("暂无笔记。")
    else:
        for row in notes.itertuples():
            with st.container(border=True):
                st.caption(row.created_at)
                st.write(row.note)
                if st.button("删除", key=f"delete-note-{row.note_id}"):
                    delete_note(db, row.note_id)
                    st.rerun()

elif page == "国内基金排行":
    title("基金排行", "同类比较用于发现候选，不用短期冠军替代基金研究。")
    category = st.selectbox("基金类型", ["全部", "股票型", "混合型", "债券型", "指数型", "QDII"])
    source_badge("AKShare / 东方财富开放基金排行")
    if st.button("联网获取排行", type="primary"):
        try:
            with st.spinner("正在获取真实基金排行…"):
                st.session_state["fund_ranking"] = fund_rank(category)
        except Exception as error:
            st.error(f"未取得排行数据：{error}")
    ranking = st.session_state.get("fund_ranking")
    if isinstance(ranking, pd.DataFrame) and not ranking.empty:
        useful = [c for c in ["序号", "基金代码", "基金简称", "日期", "单位净值", "近1月", "近3月", "近1年", "近3年", "成立来", "手续费"] if c in ranking.columns]
        st.dataframe(ranking[useful].head(200), hide_index=True, width="stretch")
        if "基金代码" in ranking.columns:
            candidate = st.selectbox("继续研究基金", ranking["基金代码"].astype(str).str.zfill(6).head(200), format_func=lambda value: f"{value} · {ranking.loc[ranking['基金代码'].astype(str).str.zfill(6) == value, '基金简称'].iloc[0]}" if "基金简称" in ranking.columns else value)
            a, b = st.columns(2)
            if a.button("进入基金分析", width="stretch"):
                st.session_state["active_fund"] = candidate
                st.session_state["page"] = "国内基金分析"
                st.rerun()
            if b.button("加入基金自选", width="stretch"):
                name = ranking.loc[ranking["基金代码"].astype(str).str.zfill(6) == candidate, "基金简称"].iloc[0] if "基金简称" in ranking.columns else candidate
                save_watchlist_item(db, candidate, name, "fund")
                st.success("已加入基金自选。")
        st.caption("排行仅用于同类候选发现，不代表基金质量结论；费率、规模、经理任期、持仓与基准仍需在基金公告中复核。")
    else:
        st.markdown('<div class="empty">点击按钮联网获取。没有成功前不展示排行。</div>', unsafe_allow_html=True)

elif page == "国内基金分析":
    title("基金分析", "把收益、波动和最大回撤放在一张研究卡里。")
    fund_code = st.text_input("基金代码", value=str(st.session_state.get("active_fund", "161725")), max_chars=6)
    source_badge("AKShare / 东方财富基金净值")
    if st.button("联网分析", type="primary"):
        try:
            with st.spinner("正在获取真实净值历史…"):
                frame = cached_fund_history(db, fund_code, refresh=True)
            if frame.empty:
                st.error("没有取得该基金的净值数据。")
            else:
                st.session_state["active_fund"] = fund_code
                st.session_state[f"fund-{fund_code}"] = frame
        except Exception as error:
            st.error(f"基金数据获取失败：{error}")
    frame = st.session_state.get(f"fund-{fund_code}")
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        summary = fund_summary(frame)
        source_badge(f"真实{frame.attrs.get('nav_kind', '净值')}历史", frame.date.max().strftime("%Y-%m-%d"))
        if frame.attrs.get("cache_status") == "stale":
            st.warning(f"基金净值刷新失败，当前显示上次成功缓存（{frame.attrs.get('refresh_error')}）。")
        if not summary["total_return_compatible"]:
            st.warning("累计净值接口不可用，当前只有单位净值。单位净值会遗漏分红影响，因此拒绝计算收益、波动和回撤。")
        a, b, c, d = st.columns(4)
        a.metric("最新净值", f"{summary['nav']:.4f}")
        b.metric("近1年", pct(summary["return_1y"]))
        c.metric("年化波动", pct(summary["annualized_volatility"]))
        d.metric("成立来最大回撤", pct(summary["max_drawdown"]))
        left, right = st.columns(2)
        left.line_chart(frame.set_index("date")["nav"], height=360)
        right.area_chart(frame.set_index("date")["drawdown"], height=360)
        if st.button("加入基金自选"):
            save_watchlist_item(db, fund_code, fund_code, "fund")
            st.success("已加入。")
        if st.button("联网加载基金档案、费用、基准与持仓"):
            with st.spinner("正在读取公开基金档案，各部分独立容错…"):
                st.session_state[f"fund-profile-{fund_code}"] = fund_profile(fund_code)
        profile = st.session_state.get(f"fund-profile-{fund_code}")
        if isinstance(profile, dict) and profile:
            st.subheader("基金公开档案")
            for section, data in profile.items():
                with st.expander(section, expanded=section == "基本资料"):
                    st.dataframe(data, hide_index=True, width="stretch")
            st.caption("基金规模、经理、费率、持仓和基准以基金最新公告为最终依据；公开接口缺失的部分不会补造。")
    else:
        st.markdown('<div class="empty">输入代码后联网分析。页面不会使用示例净值。</div>', unsafe_allow_html=True)

elif page == "全球ETF":
    title("全球 ETF", "用真实 ETF 行情观察全球股票、区域市场、黄金和房地产。")
    if st.button("联网刷新 ETF", type="primary"):
        with st.spinner("正在获取真实 ETF 行情…"):
            st.session_state["global-etfs"] = market_snapshot("全球ETF", db)
    snapshot = st.session_state.get("global-etfs")
    if isinstance(snapshot, pd.DataFrame) and not snapshot.empty:
        success = snapshot[snapshot.status != "failed"]
        failed = snapshot[snapshot.status == "failed"]
        if not success.empty:
            source_badge("Yahoo Finance chart + 本地缓存", success.as_of.max())
            st.dataframe(success[["name", "symbol", "currency", "last", "return_1m", "return_3m", "return_1y", "volatility", "max_drawdown"]].rename(columns={"name":"ETF", "symbol":"代码", "currency":"币种", "last":"最新", "return_1m":"1月", "return_3m":"3月", "return_1y":"1年", "volatility":"波动", "max_drawdown":"最大回撤"}), hide_index=True, width="stretch", column_config={x:st.column_config.NumberColumn(format="%.2%%") for x in ["1月", "3月", "1年", "波动", "最大回撤"]})
        if not failed.empty:
            st.warning(f"{len(failed)} 只 ETF 获取失败，可稍后重新刷新。")
        snapshot_actions(success, "etf")
    else:
        st.markdown('<div class="empty">点击按钮联网获取真实 ETF 数据。</div>', unsafe_allow_html=True)

elif page == "国债利率":
    title("国债利率", "债券先看收益率曲线；价格与收益率通常反向变化。")
    source_badge("美国财政部 Daily Treasury Par Yield Curve")
    if st.button("联网更新官方收益率", type="primary"):
        try:
            with st.spinner("正在读取美国财政部官方数据…"):
                st.session_state["treasury"] = cached_treasury_yield_curve(db, refresh=True)
        except Exception as error:
            st.error(f"官方数据获取失败：{error}")
    yields = st.session_state.get("treasury")
    if not isinstance(yields, pd.DataFrame):
        yields = cached_treasury_yield_curve(db, refresh=False)
    if isinstance(yields, pd.DataFrame) and not yields.empty:
        latest = latest_yield_curve(yields)
        source_badge("美国财政部官方 CSV", yields.Date.max().strftime("%Y-%m-%d"))
        st.bar_chart(latest.set_index("期限")["收益率"], height=360)
        maturities = [c for c in ["2 Yr", "5 Yr", "10 Yr", "30 Yr"] if c in yields.columns]
        st.line_chart(yields.set_index("Date")[maturities], height=390)
        latest_row = yields.iloc[-1]
        s1, s2, s3 = st.columns(3)
        spread_2s10s = latest_row.get("10 Yr") - latest_row.get("2 Yr")
        spread_3m10y = latest_row.get("10 Yr") - latest_row.get("3 Mo")
        one_day_change = yields.iloc[-1].get("10 Yr") - yields.iloc[-2].get("10 Yr") if len(yields) >= 2 else float("nan")
        s1.metric("10年-2年", f"{spread_2s10s:.2f} 个百分点")
        s2.metric("10年-3个月", f"{spread_3m10y:.2f} 个百分点")
        s3.metric("10年期日变化", f"{one_day_change * 100:.1f} bp")
        if spread_2s10s < 0 or spread_3m10y < 0:
            st.warning("部分期限利差倒挂。这是收益率曲线形态描述，不是经济衰退的确定性预测。")
    else:
        st.markdown('<div class="empty">点击按钮联网读取官方收益率曲线。</div>', unsafe_allow_html=True)

elif page == "债券ETF":
    title("债券 ETF 价格代理", "这里只比较复权价格收益、波动与回撤；免费源未提供久期、YTM、SEC 收益率和信用利差，不能替代专业债券研究。")
    if st.button("联网刷新债券 ETF", type="primary"):
        with st.spinner("正在获取真实债券 ETF 行情…"):
            st.session_state["bond-etfs"] = market_snapshot("债券ETF", db)
    snapshot = st.session_state.get("bond-etfs")
    if isinstance(snapshot, pd.DataFrame) and not snapshot.empty:
        success = snapshot[snapshot.status != "failed"]
        failed = snapshot[snapshot.status == "failed"]
        if not success.empty:
            source_badge("Yahoo Finance chart + 本地缓存", success.as_of.max())
            st.dataframe(success[["name", "symbol", "currency", "last", "return_1m", "return_3m", "return_1y", "volatility", "max_drawdown"]].rename(columns={"name":"债券ETF", "symbol":"代码", "currency":"币种", "last":"最新", "return_1m":"1月", "return_3m":"3月", "return_1y":"1年", "volatility":"波动", "max_drawdown":"最大回撤"}), hide_index=True, width="stretch", column_config={x:st.column_config.NumberColumn(format="%.2%%") for x in ["1月", "3月", "1年", "波动", "最大回撤"]})
        if not failed.empty:
            st.warning(f"{len(failed)} 只债券 ETF 获取失败，可稍后重新刷新。")
        snapshot_actions(success, "bond")
    else:
        st.markdown('<div class="empty">点击按钮联网获取。ETF 仅用于市场观察，不代表直接持有国债。</div>', unsafe_allow_html=True)

elif page == "黄金与商品":
    title("黄金与商品", "真实期货连续行情用于趋势观察；不等同于国内实物金或具体合约成交价。")
    if st.button("联网刷新商品", type="primary"):
        with st.spinner("正在获取黄金、白银、原油等真实行情…"):
            st.session_state["commodities"] = market_snapshot("商品", db)
    snapshot = st.session_state.get("commodities")
    if isinstance(snapshot, pd.DataFrame) and not snapshot.empty:
        success = snapshot[snapshot.status != "failed"]
        failed = snapshot[snapshot.status == "failed"]
        if not success.empty:
            source_badge("Yahoo Finance 期货连续行情 + 本地缓存", success.as_of.max())
            st.dataframe(success[["name", "symbol", "currency", "last", "return_1m", "return_3m", "return_1y", "volatility", "max_drawdown"]].rename(columns={"name":"商品连续合约", "symbol":"代码", "currency":"币种", "last":"最新", "return_1m":"1月", "return_3m":"3月", "return_1y":"1年", "volatility":"波动", "max_drawdown":"最大回撤"}), hide_index=True, width="stretch", column_config={x:st.column_config.NumberColumn(format="%.2%%") for x in ["1月", "3月", "1年", "波动", "最大回撤"]})
            st.bar_chart(success.set_index("name")["return_3m"], height=300)
            gold_row = success[success.symbol == "GC=F"]
            if not gold_row.empty:
                try:
                    fx, _ = cached_asset_history(db, "USDCNY=X", period="1mo")
                    gld, gld_source = cached_asset_history(db, "GLD", period="1y")
                    implied_cny_g = float(gold_row.iloc[0]["last"]) * float(fx.close.iloc[-1]) / 31.1034768
                    gld_summary = asset_summary(gld)
                    st.subheader("黄金的不同代理")
                    a, b, c = st.columns(3)
                    a.metric("COMEX 连续期货", f"${float(gold_row.iloc[0]['last']):,.2f}/盎司")
                    b.metric("期货折算人民币", f"¥{implied_cny_g:,.2f}/克")
                    c.metric("黄金 ETF GLD", f"${gld_summary['last']:,.2f}", pct(gld_summary["return_1y"]))
                    st.caption(f"期货人民币克价 = 连续期货 × USDCNY ÷ 31.1034768，只是换月影响下的期货折算，不是上海金交所现货价；GLD 是 ETF 每份价格。GLD 来源：{gld_source}。")
                except Exception as error:
                    st.warning(f"黄金 ETF 或汇率代理暂未取得：{type(error).__name__}")
        if not failed.empty:
            st.warning(f"{len(failed)} 个商品连续合约获取失败，可稍后重新刷新。")
        snapshot_actions(success, "commodity")
    else:
        st.markdown('<div class="empty">点击按钮联网获取真实商品行情。</div>', unsafe_allow_html=True)

elif page == "重要事件":
    title("重要事件", "提前知道日期，不提前猜测政策结果。")
    days = st.segmented_control("范围", [7, 30, 90, 365], default=90, format_func=lambda n: f"未来 {n} 天")
    events = upcoming_events(db, days or 90)
    source_badge("美联储日历联网同步；欧洲央行、日本银行、英格兰银行与 BLS 官方核验缓存", "2026-08-14")
    render_events(events, 100)
    st.info("央行可能加息、降息或维持利率，宏观数据也可能修订。这里记录官方发布日期，不预测结果；缓存日历应定期与来源链接复核。")

elif page == "自定义提醒":
    title("自定义提醒", "把财报、基金开放期和个人复盘日加入本地提醒。")
    due = due_reminders(db)
    if not due.empty:
        st.subheader("当前提醒")
        render_events(due, 20)
    with st.form("event-form"):
        event_date = st.date_input("日期", min_value=date.today())
        event_title = st.text_input("事件名称")
        category = st.selectbox("类型", ["公司公告", "财报", "基金", "宏观数据", "其他"])
        importance = st.selectbox("重要性", ["高", "中", "低"])
        reminder_days = st.number_input("提前提醒天数", 0, 90, 7)
        description = st.text_area("备注")
        if st.form_submit_button("保存提醒", type="primary"):
            if not event_title.strip():
                st.error("请填写事件名称。")
            else:
                add_custom_event(db, event_date, event_title, category, importance, description, int(reminder_days))
                st.success("已保存。")
                st.rerun()
    custom = db.query_df("SELECT event_id, event_date, title, reminder_days FROM events WHERE is_custom=1 ORDER BY event_date")
    if not custom.empty:
        st.subheader("已保存")
        st.dataframe(custom[["event_date", "title", "reminder_days"]].rename(columns={"event_date":"日期", "title":"事件", "reminder_days":"提前天数"}), hide_index=True, width="stretch")
        target = st.selectbox("删除提醒", custom.event_id, format_func=lambda x: custom.loc[custom.event_id == x, "title"].iloc[0])
        if st.button("删除所选"):
            delete_custom_event(db, target)
            st.rerun()

elif page == "数据管理":
    title("数据管理", "所有选股先有真实数据，再有计算结果。")
    status = db.query_df("SELECT COUNT(*) rows, COUNT(DISTINCT code) codes, MIN(trade_date) first_date, MAX(trade_date) latest FROM daily_prices").iloc[0]
    runs = db.query_df("SELECT * FROM runs ORDER BY created_at DESC LIMIT 1")
    a, b, c, d = st.columns(4)
    a.metric("股票数", int(status.codes))
    b.metric("日线记录", int(status.rows))
    c.metric("起始日期", status.first_date or "暂无")
    d.metric("最新日期", status.latest or "暂无")
    source_badge("联网行情：东方财富；不可用时腾讯回退。本地存储：SQLite")
    st.warning("首次完整更新会下载较多历史行情，可能持续数分钟。运行期间请保持网络连接。")
    quick, full = st.columns(2)
    if quick.button("快速初始化 30 只", type="primary", width="stretch"):
        quick_settings = replace(settings, universe_size=30, top_n=min(settings.top_n, 15))
        try:
            with exclusive_job(db, ROOT / "data" / ".writer.lock", "a_share_quick") as job:
                with st.spinner("正在联网获取真实行情并计算，请勿关闭页面…"):
                    result = sync_data(quick_settings, workers=6)
                job["succeeded"] = result["updated"]
                job["failed"] = len(result["failures"])
                if result["failures"]:
                    job["message"] = f"source={result['source']} failures={len(result['failures'])}; 未生成候选"
                    picks, report = pd.DataFrame(), None
                else:
                    picks, report = run_selection(quick_settings)
                    job["message"] = f"source={result['source']} report={report}"
            if result["failures"]:
                st.warning(f"部分完成：{len(result['failures'])} 只股票失败，任务已记为 partial，未生成候选。请稍后重试。")
            else:
                st.success(f"完成：股票池 {result['universe']} 只，生成 {len(picks)} 个候选。数据已写入本机。")
        except Exception as error:
            st.error(f"更新失败，没有生成替代数据：{error}")
    if full.button(f"完整更新 {settings.universe_size} 只", width="stretch"):
        try:
            with exclusive_job(db, ROOT / "data" / ".writer.lock", "a_share_full") as job:
                with st.spinner("正在完整联网更新，首次可能需要数分钟…"):
                    result = sync_data(settings, workers=6)
                job["succeeded"] = result["updated"]
                job["failed"] = len(result["failures"])
                if result["failures"]:
                    job["message"] = f"source={result['source']} failures={len(result['failures'])}; 未生成候选"
                    picks, report = pd.DataFrame(), None
                else:
                    picks, report = run_selection(settings)
                    job["message"] = f"source={result['source']} report={report}"
            if result["failures"]:
                st.warning(f"部分完成：{len(result['failures'])} 只股票失败，任务已记为 partial，未生成候选。请稍后重试。")
            else:
                st.success(f"完成：股票池 {result['universe']} 只，生成 {len(picks)} 个候选。")
        except Exception as error:
            st.error(f"更新失败，没有生成替代数据：{error}")
    if st.button("同步全球行情、基金、美债与事件", width="stretch"):
        try:
            with exclusive_job(db, ROOT / "data" / ".writer.lock", "multiasset_full") as job:
                with st.spinner("正在并行更新全球行情、你的基金、美债曲线和事件缓存…"):
                    result = sync_multi_asset_data(db, workers=6)
                job["succeeded"] = result["succeeded"]
                job["failed"] = result["failed"]
                job["message"] = f"symbols={result['symbols']} funds={result['funds']}"
            if result["failed"]:
                st.warning(f"多资产任务部分完成：成功 {result['succeeded']}，失败 {result['failed']}。失败项已记录，可重试。")
            else:
                st.success(f"多资产任务完成：成功更新 {result['succeeded']} 个数据集合。")
        except Exception as error:
            st.error(f"多资产更新失败：{error}")
    if not runs.empty:
        st.caption(f"上次成功计算：{runs.iloc[0].created_at} · 数据日 {runs.iloc[0].as_of_date}")
    st.subheader("多资产数据质量")
    quality = db.query_df("""
        SELECT p.symbol,
               SUM(CASE WHEN p.price_kind NOT IN ('legacy_unknown','unknown') THEN 1 ELSE 0 END) AS records,
               SUM(CASE WHEN p.price_kind IN ('legacy_unknown','unknown') THEN 1 ELSE 0 END) AS isolated_legacy,
               MIN(CASE WHEN p.price_kind NOT IN ('legacy_unknown','unknown') THEN p.price_date END) AS first_date,
               MAX(p.price_date) AS latest_date, MAX(p.fetched_at) AS fetched_at,
               MAX(p.source) AS source, MAX(p.price_kind) AS price_kind, MAX(m.currency) AS currency,
               MAX(m.exchange_timezone) AS timezone
        FROM asset_prices p LEFT JOIN asset_metadata m ON p.symbol=m.symbol
        GROUP BY p.symbol ORDER BY p.symbol
    """)
    if quality.empty:
        st.caption("尚未缓存全球资产行情。")
    else:
        latest_fetch = pd.to_datetime(quality.fetched_at, errors="coerce")
        quality["状态"] = latest_fetch.apply(lambda value: "当天抓取" if pd.notna(value) and value.date() == date.today() else "历史缓存")
        st.dataframe(quality.rename(columns={"symbol":"代码", "records":"可用记录", "isolated_legacy":"已隔离旧记录", "first_date":"可用起始日", "latest_date":"最新交易日", "fetched_at":"抓取时间", "source":"来源", "price_kind":"价格口径", "currency":"币种", "timezone":"市场时区"}), hide_index=True, width="stretch")
    st.subheader("A股选股运行")
    history_runs = db.query_df("SELECT as_of_date, created_at, universe_count, scored_count, status, message FROM runs ORDER BY created_at DESC LIMIT 20")
    if history_runs.empty:
        st.caption("尚无选股运行。")
    else:
        st.dataframe(history_runs.rename(columns={"as_of_date":"数据日", "created_at":"运行时间", "universe_count":"股票池", "scored_count":"有效评分", "status":"状态", "message":"质量信息"}), hide_index=True, width="stretch")
    st.subheader("数据任务记录")
    jobs = db.query_df("SELECT * FROM data_jobs ORDER BY started_at DESC LIMIT 30")
    if jobs.empty:
        st.caption("尚无网页数据任务。")
    else:
        st.dataframe(jobs.rename(columns={"job_type":"任务", "started_at":"开始", "finished_at":"结束", "status":"状态", "succeeded":"成功", "failed":"失败", "message":"信息"}), hide_index=True, width="stretch")

elif page == "评分说明":
    title("评分说明", "规则透明、边界明确，避免把分数误解为上涨概率。")
    weights = pd.DataFrame({"因子":["趋势", "风险", "估值", "流动性", "稳定性"], "权重":[35, 25, 20, 10, 10]}).set_index("因子")
    st.bar_chart(weights, height=320)
    st.markdown("""
    - **趋势**：20/60/120 日历史收益、是否站上 60 日均线。
    - **风险**：历史波动和近 120 日最大回撤。
    - **估值**：有效 PE/PB 在当日候选池中的相对位置。
    - **流动性**：近 20 日真实成交额。
    - **稳定性**：近 24 个交易周中上涨周占比。
    """)
    st.warning("综合分是横截面研究排序，不是收益预测、目标价或买入建议。企业基本面必须继续查看财务质量、公告与研究笔记。")
    st.info("正式候选硬门槛：PE 必须有效且不高于配置上限、120 日最大回撤不低于 -40%、20 日年化波动不高于 80%。当 PB 覆盖不足 50% 时，估值因子只使用 PE，不给缺失 PB 奖励。")

st.markdown('<div class="foot">所有行情、财务和基金数字均来自联网接口或本地真实缓存；获取失败时显示失败，不生成替代数值。知衡仅用于个人研究，不构成投资建议。</div>', unsafe_allow_html=True)
