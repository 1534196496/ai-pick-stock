from datetime import date

from stock_picker.db import Database
from stock_picker.events import add_custom_event, due_reminders, event_local_time, refresh_fomc_events, seed_official_events, upcoming_events


def test_official_and_custom_event_reminders(tmp_path):
    db = Database(tmp_path / "events.db")
    seed_official_events(db)
    september = upcoming_events(db, days=40, today=date(2026, 8, 13))
    assert "美联储 FOMC 利率决议" in september["title"].tolist()
    decision = september[september["title"] == "美联储 FOMC 利率决议"].iloc[0]
    assert decision["event_date"] == "2026-09-16"
    assert "欧洲央行货币政策决议" in september["title"].tolist()
    assert "日本银行货币政策决议" in september["title"].tolist()
    assert "美国消费者价格指数（CPI）发布" in september["title"].tolist()
    assert "美国就业报告（非农）发布" in september["title"].tolist()
    assert "英格兰银行 MPC 利率决议" in september["title"].tolist()
    assert decision["event_time"] == "14:00"
    assert decision["event_timezone"] == "America/New_York"
    add_custom_event(db, date(2026, 8, 18), "示例财报", "财报", "高", "测试", 7)
    due = due_reminders(db, today=date(2026, 8, 13))
    assert "示例财报" in due["title"].tolist()


def test_live_fomc_parser_uses_decision_and_minutes_dates(tmp_path):
    db = Database(tmp_path / "events.db")
    html = """
    <div class='panel'><div class='panel-heading'><h4><a>2027 FOMC Meetings</a></h4></div>
      <div class='fomc-meeting'><span class='fomc-meeting__month'>March</span>
      <span class='fomc-meeting__date'>16-17*</span><span class='fomc-meeting__minutes'>Minutes (Released April 07, 2027)</span></div>
    </div>"""
    assert refresh_fomc_events(db, html) == 2
    rows = db.query_df("SELECT * FROM events ORDER BY event_date")
    assert rows.event_date.tolist() == ["2027-03-17", "2027-04-07"]
    assert set(rows.verification_status) == {"official_live_sync"}


def test_seed_does_not_overwrite_live_fomc_or_future_minutes(tmp_path):
    db = Database(tmp_path / "events.db")
    seed_official_events(db)
    html = """<div class='panel'><div class='panel-heading'><h4><a>2027 FOMC Meetings</a></h4></div>
      <div class='fomc-meeting'><span class='fomc-meeting__month'>March</span><span class='fomc-meeting__date'>16-17*</span></div></div>"""
    refresh_fomc_events(db, html)
    seed_official_events(db)
    live = db.query_df("SELECT verification_status FROM events WHERE event_id='fomc-2027-03-17'").iloc[0]
    assert live.verification_status == "official_live_sync"
    assert not db.query_df("SELECT * FROM events WHERE event_id='fomc-minutes-2026-07-29'").empty


def test_event_time_converts_to_shanghai():
    # September is daylight-saving time in New York: 14:00 ET = 02:00 next day Shanghai.
    assert event_local_time("2026-09-16", "14:00", "America/New_York") == "2026-09-17 02:00"
    assert event_local_time("2026-09-16", float("nan"), "America/New_York") is None
