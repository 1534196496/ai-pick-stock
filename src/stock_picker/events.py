from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import re
from zoneinfo import ZoneInfo

import pandas as pd

from .db import Database


FED_SOURCE = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
ECB_SOURCE = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"
BOJ_SOURCE = "https://www.boj.or.jp/en/mopo/mpmsche_minu/"
BLS_SOURCE = "https://www.bls.gov/schedule/2026/"
BOE_SOURCE = "https://www.bankofengland.co.uk/news/2024/december/mpc-dates-for-2026"
OFFICIAL_VERIFIED_AT = "2026-08-14T00:00:00+08:00"

# Explicit official meeting dates. The product alerts on the decision day
# (meeting end), not the first meeting day. It never infers the policy result.
FOMC_MEETINGS = [
    ("2026-01-27", "2026-01-28", False),
    ("2026-03-17", "2026-03-18", True),
    ("2026-04-28", "2026-04-29", False),
    ("2026-06-16", "2026-06-17", True),
    ("2026-07-28", "2026-07-29", False),
    ("2026-09-15", "2026-09-16", True),
    ("2026-10-27", "2026-10-28", False),
    ("2026-12-08", "2026-12-09", True),
    ("2027-01-26", "2027-01-27", False),
]

ECB_DECISIONS = ["2026-09-10", "2026-10-29", "2026-12-17"]
BOJ_DECISIONS = ["2026-09-18", "2026-10-30", "2026-12-18"]
BLS_CPI_RELEASES = ["2026-09-11", "2026-10-14", "2026-11-10", "2026-12-10"]
BLS_EMPLOYMENT_RELEASES = ["2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04"]
BOE_DECISIONS = ["2026-09-17", "2026-11-05", "2026-12-17"]


def seed_official_events(db: Database) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    rows = []
    for start, end, projections in FOMC_MEETINGS:
        detail = "利率决定及新闻发布会；本次同时发布经济预测与点阵图" if projections else "利率决定及新闻发布会"
        rows.append((
            f"fomc-{end}", end, end, "美联储 FOMC 利率决议", "央行决议", "高", "美国",
            f"会议期 {start} 至 {end}；{detail}。可能加息、降息或维持利率，结果以正式声明为准。",
            FED_SOURCE, 7, 0, now,
        ))
    # Exact future release published by the Federal Reserve calendar; do not
    # create other minute dates by adding an assumed 21 days.
    rows.append((
        "fomc-minutes-2026-07-29", "2026-08-19", None, "美联储 FOMC 会议纪要", "会议纪要", "中", "美国",
        "2026-07-28 至 2026-07-29 会议的纪要，官方日历列示于 2026-08-19 发布。",
        FED_SOURCE, 3, 0, now,
    ))
    for decision in ECB_DECISIONS:
        rows.append((
            f"ecb-{decision}", decision, decision, "欧洲央行货币政策决议", "央行决议", "高", "欧元区",
            "欧洲央行管理委员会货币政策会议第二日，随后举行新闻发布会；结果以欧洲央行正式声明为准。",
            ECB_SOURCE, 7, 0, now,
        ))
    for decision in BOJ_DECISIONS:
        rows.append((
            f"boj-{decision}", decision, decision, "日本银行货币政策决议", "央行决议", "高", "日本",
            "日本银行货币政策会议结束日；声明发布时间可能未预先确定，结果以日本银行正式发布为准。",
            BOJ_SOURCE, 7, 0, now,
        ))
    for release in BLS_CPI_RELEASES:
        rows.append((
            f"bls-cpi-{release}", release, release, "美国消费者价格指数（CPI）发布", "宏观数据", "高", "美国",
            "美国劳工统计局按官方日历于美东时间 08:30 发布；实际值与修订以 BLS 正式发布为准。",
            BLS_SOURCE, 3, 0, now,
        ))
    for release in BLS_EMPLOYMENT_RELEASES:
        rows.append((
            f"bls-employment-{release}", release, release, "美国就业报告（非农）发布", "宏观数据", "高", "美国",
            "美国劳工统计局 Employment Situation，官方日历时间为美东 08:30；结果与修订以 BLS 为准。",
            BLS_SOURCE, 3, 0, now,
        ))
    for decision in BOE_DECISIONS:
        rows.append((
            f"boe-{decision}", decision, decision, "英格兰银行 MPC 利率决议", "央行决议", "高", "英国",
            "英格兰银行货币政策委员会决议与会议纪要发布日；结果以英国央行正式声明为准。",
            BOE_SOURCE, 7, 0, now,
        ))
    with db.connect() as con:
        con.executemany(
            """INSERT INTO events(event_id,event_date,end_date,title,category,importance,region,description,source_url,reminder_days,is_custom,updated_at,event_timezone,verification_status,last_verified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'official_cached', ?)
            ON CONFLICT(event_id) DO UPDATE SET event_date=excluded.event_date,
            end_date=excluded.end_date, title=excluded.title, category=excluded.category,
            importance=excluded.importance, region=excluded.region,
            description=excluded.description, source_url=excluded.source_url,
            reminder_days=excluded.reminder_days, updated_at=excluded.updated_at""",
            [(*row, "按来源所在地", OFFICIAL_VERIFIED_AT) for row in rows],
        )
        con.execute("UPDATE events SET event_time='14:00', event_timezone='America/New_York' WHERE event_id LIKE 'fomc-%'")
        con.execute("UPDATE events SET event_time='08:30', event_timezone='America/New_York' WHERE event_id LIKE 'bls-%'")
        con.execute("UPDATE events SET event_timezone='Europe/London' WHERE event_id LIKE 'boe-%'")
        con.execute("UPDATE events SET event_timezone='Europe/Berlin' WHERE event_id LIKE 'ecb-%'")
        con.execute("UPDATE events SET event_timezone='Asia/Tokyo' WHERE event_id LIKE 'boj-%'")


def refresh_fomc_events(db: Database, html: str | None = None) -> int:
    """Synchronize FOMC meetings/minutes from the live Federal Reserve calendar."""
    from bs4 import BeautifulSoup
    import requests

    if html is None:
        response = requests.get(FED_SOURCE, headers={"User-Agent":"Mozilla/5.0"}, timeout=25)
        response.raise_for_status()
        html = response.text
    soup = BeautifulSoup(html, "html.parser")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = []
    for heading_text in soup.find_all(string=lambda text: bool(text and re.fullmatch(r"20\d{2} FOMC Meetings", text.strip()))):
        year = int(heading_text.strip()[:4])
        if year < date.today().year:
            continue
        panel = heading_text.parent.parent.parent.parent
        for meeting in panel.select(".fomc-meeting"):
            month_node = meeting.select_one(".fomc-meeting__month")
            date_node = meeting.select_one(".fomc-meeting__date")
            if not month_node or not date_node:
                continue
            month = month_node.get_text(" ", strip=True)
            date_text = date_node.get_text(" ", strip=True)
            numbers = [int(value) for value in re.findall(r"\d+", date_text)]
            if not numbers:
                continue
            start_day, end_day = numbers[0], numbers[-1]
            month_parts = month.split("/")
            start_month, end_month = month_parts[0], month_parts[-1]
            def parse_meeting_date(month_name: str, day: int) -> str:
                for fmt in ("%Y %B %d", "%Y %b %d"):
                    try:
                        return datetime.strptime(f"{year} {month_name} {day}", fmt).date().isoformat()
                    except ValueError:
                        continue
                raise ValueError(f"无法解析FOMC日期: {year} {month_name} {day}")
            start = parse_meeting_date(start_month, start_day)
            end = parse_meeting_date(end_month, end_day)
            projections = "*" in date_text
            description = f"会议期 {start} 至 {end}；利率决定及新闻发布会" + ("，同时发布经济预测与点阵图" if projections else "") + "。结果以正式声明为准。"
            rows.append((f"fomc-{end}", end, end, "美联储 FOMC 利率决议", "央行决议", "高", "美国", description, FED_SOURCE, 7, 0, now, "14:00", "America/New_York", "official_live_sync", now))
            released = re.search(r"Released\s+([A-Za-z]+\s+\d{1,2},\s+20\d{2})", meeting.get_text(" ", strip=True))
            if released:
                minutes_date = datetime.strptime(released.group(1), "%B %d, %Y").date().isoformat()
                rows.append((f"fomc-minutes-{end}", minutes_date, None, "美联储 FOMC 会议纪要", "会议纪要", "中", "美国", f"{start} 至 {end} 会议的纪要，发布日期来自美联储实时日历。", FED_SOURCE, 3, 0, now, "14:00", "America/New_York", "official_live_sync", now))
    if not rows:
        raise RuntimeError("美联储官方页面结构校验失败：未解析到会议")
    with db.connect() as con:
        con.execute(
            """DELETE FROM events WHERE is_custom=0 AND event_id LIKE 'fomc-%'
            AND (event_id NOT LIKE 'fomc-minutes-%' OR event_date <= ?)""",
            (date.today().isoformat(),),
        )
        con.executemany(
            """INSERT INTO events(event_id,event_date,end_date,title,category,importance,region,description,source_url,reminder_days,is_custom,updated_at,event_time,event_timezone,verification_status,last_verified)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    return len(rows)


def add_custom_event(
    db: Database,
    event_date: date,
    title: str,
    category: str,
    importance: str,
    description: str,
    reminder_days: int,
) -> None:
    digest = hashlib.sha1(f"{event_date}:{title}".encode()).hexdigest()[:12]
    with db.connect() as con:
        con.execute(
            """INSERT OR REPLACE INTO events(event_id,event_date,end_date,title,category,importance,region,description,source_url,reminder_days,is_custom,updated_at,verification_status,last_verified)
            VALUES (?, ?, NULL, ?, ?, ?, ?, ?, NULL, ?, 1, ?, 'user_entered', ?)""",
            (
                f"custom-{digest}", event_date.isoformat(), title.strip(), category,
                importance, "自定义", description.strip(), reminder_days,
                datetime.now().isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds"),
            ),
        )


def delete_custom_event(db: Database, event_id: str) -> None:
    with db.connect() as con:
        con.execute("DELETE FROM events WHERE event_id=? AND is_custom=1", (event_id,))


def upcoming_events(db: Database, days: int = 30, today: date | None = None) -> pd.DataFrame:
    today = today or date.today()
    end = today + timedelta(days=days)
    frame = db.query_df(
        "SELECT * FROM events WHERE event_date BETWEEN ? AND ? ORDER BY event_date, importance",
        (today.isoformat(), end.isoformat()),
    )
    if not frame.empty:
        frame["days_left"] = (pd.to_datetime(frame["event_date"]) - pd.Timestamp(today)).dt.days
    return frame


def due_reminders(db: Database, today: date | None = None) -> pd.DataFrame:
    today = today or date.today()
    frame = upcoming_events(db, days=90, today=today)
    if frame.empty:
        return frame
    return frame[frame["days_left"] <= frame["reminder_days"]].copy()


def event_local_time(event_date: str, event_time: str | None, source_timezone: str | None, target_timezone: str = "Asia/Shanghai") -> str | None:
    if not event_time or not source_timezone or pd.isna(event_time) or pd.isna(source_timezone):
        return None
    try:
        source = datetime.fromisoformat(f"{event_date}T{event_time}").replace(tzinfo=ZoneInfo(str(source_timezone)))
        local = source.astimezone(ZoneInfo(target_timezone))
        return local.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, KeyError):
        return None
