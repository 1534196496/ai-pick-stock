from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class Settings:
    root: Path
    database: Path
    reports: Path
    provider: str
    adjust: str
    history_calendar_days: int
    universe_size: int
    min_listing_days: int
    min_daily_amount_cny: float
    exclude_name_keywords: tuple[str, ...]
    top_n: int
    max_pe: float
    max_pb: float
    weights: dict[str, float]
    ai_enabled: bool
    ai_model: str


def load_settings(path: str | Path = "config.toml") -> Settings:
    config_path = Path(path).resolve()
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    root = config_path.parent
    paths = raw["paths"]
    market = raw["market"]
    selection = raw["selection"]
    weights = {key: float(value) for key, value in raw["weights"].items()}
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ValueError("[weights] 权重之和必须为 1")
    return Settings(
        root=root,
        database=(root / paths["database"]).resolve(),
        reports=(root / paths["reports"]).resolve(),
        provider=market["provider"],
        adjust=market["adjust"],
        history_calendar_days=int(market["history_calendar_days"]),
        universe_size=int(market["universe_size"]),
        min_listing_days=int(market["min_listing_days"]),
        min_daily_amount_cny=float(market["min_daily_amount_cny"]),
        exclude_name_keywords=tuple(market["exclude_name_keywords"]),
        top_n=int(selection["top_n"]),
        max_pe=float(selection["max_pe"]),
        max_pb=float(selection["max_pb"]),
        weights=weights,
        ai_enabled=bool(raw.get("ai", {}).get("enabled", False)),
        ai_model=str(raw.get("ai", {}).get("model", "gpt-5.6-luna")),
    )

