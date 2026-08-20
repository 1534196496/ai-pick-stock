from __future__ import annotations

import argparse
import json

from .config import load_settings
from .db import Database
from .events import due_reminders, seed_official_events


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.toml")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    settings = load_settings(args.config)
    db = Database(settings.database)
    seed_official_events(db)
    frame = due_reminders(db)
    items = frame[["event_date", "title", "days_left", "importance"]].to_dict("records") if not frame.empty else []
    if args.json:
        print(json.dumps(items, ensure_ascii=False))
    elif not items:
        print("近期没有达到提醒条件的重要事件。")
    else:
        for item in items:
            when = "今天" if item["days_left"] == 0 else f"{item['days_left']} 天后"
            print(f"[{item['importance']}] {when} · {item['event_date']} · {item['title']}")


if __name__ == "__main__":
    main()
