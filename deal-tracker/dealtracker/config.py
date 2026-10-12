from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields

from .models import Watch

WATCH_KEYS = {f.name for f in fields(Watch)}


@dataclass
class Config:
    interval: int
    db_path: str
    vinted: dict
    marketplace: dict
    notify: dict
    watches: list[Watch]


def load(path: str) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    defaults = raw.get("defaults", {})
    watches = []
    for w in raw.get("watch", []):
        merged = {**defaults, **w}
        # Per-watch excludes add to the defaults instead of replacing them.
        merged["exclude"] = list(defaults.get("exclude", [])) + list(w.get("exclude", []))
        unknown = set(merged) - WATCH_KEYS
        if unknown:
            raise ValueError(f"watch '{w.get('name')}': unknown keys {sorted(unknown)}")
        watches.append(Watch(**merged))
    if not watches:
        raise ValueError("config has no [[watch]] entries")

    return Config(
        interval=int(raw.get("interval", 600)),
        db_path=raw.get("db_path", "deals.db"),
        vinted=raw.get("vinted", {}),
        marketplace=raw.get("marketplace", {}),
        notify=raw.get("notify", {}),
        watches=watches,
    )
