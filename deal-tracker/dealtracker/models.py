from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Listing:
    source: str            # "vinted" | "marketplace"
    item_id: str
    title: str
    price: float | None    # None = price couldn't be parsed
    currency: str
    url: str
    location: str = ""
    image: str = ""
    condition: str = ""
    posted_at: float | None = None  # unix timestamp, if the source exposes it

    @property
    def key(self) -> str:
        return f"{self.source}:{self.item_id}"


@dataclass
class Watch:
    name: str
    query: str
    min_price: float | None = None
    max_price: float | None = None
    market_price: float | None = None   # manual "fair price" override
    target_price: float | None = None   # always alert at/below this
    steal_ratio: float = 0.65
    min_ratio: float = 0.15
    min_samples: int = 8
    history_days: int = 45
    require: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=lambda: ["vinted", "marketplace"])
    vinted_params: dict = field(default_factory=dict)
