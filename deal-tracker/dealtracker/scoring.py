"""Decides whether a listing is relevant and whether it's a steal."""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from .models import Listing, Watch


def is_relevant(listing: Listing, watch: Watch) -> tuple[bool, str]:
    """Filter out junk: wrong product, broken/for-parts, empty boxes, out of price window."""
    title = listing.title.lower()
    for pattern in watch.require:
        if not re.search(pattern, title, re.IGNORECASE):
            return False, f"missing '{pattern}'"
    for pattern in watch.exclude:
        if re.search(rf"(?<!\w)(?:{pattern})(?!\w)", title, re.IGNORECASE):
            return False, f"excluded '{pattern}'"
    if listing.price is None:
        return False, "no price"
    if watch.min_price is not None and listing.price < watch.min_price:
        return False, "below min_price"
    if watch.max_price is not None and listing.price > watch.max_price:
        return False, "above max_price"
    return True, ""


@dataclass
class MarketEstimate:
    price: float | None
    samples: int
    manual: bool = False


def estimate_market(prices: list[float], watch: Watch) -> MarketEstimate:
    """Median asking price of recent relevant listings, unless the user set one."""
    if watch.market_price:
        return MarketEstimate(watch.market_price, len(prices), manual=True)
    if len(prices) < watch.min_samples:
        return MarketEstimate(None, len(prices))
    return MarketEstimate(statistics.median(prices), len(prices))


@dataclass
class Verdict:
    is_steal: bool
    discount: float | None   # 0.4 = 40% under market
    reason: str


def classify(listing: Listing, watch: Watch, market: MarketEstimate) -> Verdict:
    price = listing.price
    if price is None:
        return Verdict(False, None, "no price")

    discount = None
    if market.price:
        discount = 1 - price / market.price

    if watch.target_price is not None and price <= watch.target_price:
        return Verdict(True, discount, f"at/below your target {watch.target_price:g}")

    if not market.price:
        return Verdict(False, None, f"not enough data yet ({market.samples}/{watch.min_samples})")

    ratio = price / market.price
    if ratio < watch.min_ratio:
        return Verdict(False, discount, "suspiciously cheap (likely scam/parts/accessory)")
    if ratio <= watch.steal_ratio:
        return Verdict(True, discount, f"{discount:.0%} under market ~{market.price:.0f}")
    return Verdict(False, discount, "normal price")
