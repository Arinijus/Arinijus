"""Facebook Marketplace via a real (Playwright-driven) browser using your own logged-in profile.

Marketplace has no public API and hides results behind a login, so this opens the normal
search page and reads the listing cards. Run `python -m dealtracker fb-login` once first.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import quote, urlencode

from ..models import Listing, Watch
from .vinted import SourceError

log = logging.getLogger(__name__)

ITEM_SELECTOR = 'a[href*="/marketplace/item/"]'
_NUMBER = re.compile(r"\d[\d\s.,  ']*")
_FREE = re.compile(r"^(free|nemokamai|za darmo|gratis|kostenlos|gratuit)$", re.IGNORECASE)


def parse_price(text: str) -> float | None:
    """'€1,200' / '1 200 €' / '1.200,50 zł' / 'Free' -> float. Takes the first price in the text."""
    text = text.strip()
    if _FREE.match(text):
        return 0.0
    m = _NUMBER.search(text)
    if not m:
        return None
    num = re.sub(r"[\s  ']", "", m.group()).rstrip(".,")
    if "," in num and "." in num:
        # Whichever separator comes last is the decimal one.
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num or "." in num:
        sep = "," if "," in num else "."
        parts = num.split(sep)
        if len(parts) > 2 or len(parts[-1]) == 3:   # thousands separator: 1,200 / 1.200.000
            num = num.replace(sep, "")
        else:                                        # decimal: 12,50
            num = num.replace(sep, ".")
    try:
        return float(num)
    except ValueError:
        return None


def _looks_like_price(line: str) -> bool:
    return bool(_FREE.match(line)) or (bool(re.search(r"\d", line)) and len(line) <= 30
                                       and bool(re.search(r"[€$£]|zł|kr|eur|usd|gbp|pln", line, re.I)))


def parse_card(href: str, text: str, currency: str) -> Listing | None:
    m = re.search(r"/marketplace/item/(\d+)", href)
    if not m:
        return None
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return None

    # Card text is usually: price [old price] / title / location [/ mileage].
    price = None
    i = 0
    while i < len(lines) and _looks_like_price(lines[i]):
        if price is None:
            price = parse_price(lines[i])
        i += 1
    rest = lines[i:]
    title = rest[0] if rest else ""
    location = rest[1] if len(rest) > 1 else ""

    return Listing(
        source="marketplace",
        item_id=m.group(1),
        title=title,
        price=price,
        currency=currency,
        url=f"https://www.facebook.com/marketplace/item/{m.group(1)}/",
        location=location,
    )


def search_url(location: str, watch: Watch, radius_km: int | None, days_since_listed: int | None) -> str:
    params = {"query": watch.query, "sortBy": "creation_time_descend", "exact": "false"}
    if watch.min_price is not None:
        params["minPrice"] = int(watch.min_price)
    if watch.max_price is not None:
        params["maxPrice"] = int(watch.max_price)
    if days_since_listed:
        params["daysSinceListed"] = days_since_listed
    if radius_km:
        params["radius"] = radius_km
    return f"https://www.facebook.com/marketplace/{quote(location)}/search?{urlencode(params)}"


class MarketplaceSource:
    name = "marketplace"

    def __init__(self, location: str, profile_dir: str, currency: str = "EUR", radius_km: int | None = None,
                 days_since_listed: int | None = 1, headless: bool = True, scrolls: int = 3):
        self.location = location
        self.profile_dir = profile_dir
        self.currency = currency
        self.radius_km = radius_km
        self.days_since_listed = days_since_listed
        self.headless = headless
        self.scrolls = scrolls
        self._pw = None
        self._ctx = None

    def _context(self):
        if self._ctx is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as e:
                raise SourceError("Playwright not installed: pip install playwright && playwright install chromium") from e
            self._pw = sync_playwright().start()
            self._ctx = self._pw.chromium.launch_persistent_context(
                self.profile_dir, headless=self.headless, viewport={"width": 1280, "height": 1600})
        return self._ctx

    def search(self, watch: Watch) -> list[Listing]:
        from playwright.sync_api import TimeoutError as PWTimeout

        page = self._context().new_page()
        try:
            page.goto(search_url(self.location, watch, self.radius_km, self.days_since_listed),
                      wait_until="domcontentloaded", timeout=45_000)
            try:
                page.wait_for_selector(ITEM_SELECTOR, timeout=20_000)
            except PWTimeout:
                if "login" in page.url or page.locator('input[name="email"]').count():
                    raise SourceError("Not logged in to Facebook - run: python -m dealtracker fb-login")
                return []  # genuinely no results
            for _ in range(self.scrolls):
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(1500)
            cards = page.eval_on_selector_all(
                ITEM_SELECTOR, "els => els.map(e => ({href: e.getAttribute('href'), text: e.innerText}))")
        finally:
            page.close()

        seen, listings = set(), []
        for card in cards:
            listing = parse_card(card["href"] or "", card["text"] or "", self.currency)
            if listing and listing.item_id not in seen:
                seen.add(listing.item_id)
                listings.append(listing)
        return listings

    def close(self) -> None:
        if self._ctx:
            self._ctx.close()
        if self._pw:
            self._pw.stop()


def interactive_login(profile_dir: str) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(profile_dir, headless=False)
        page = ctx.new_page()
        page.goto("https://www.facebook.com/marketplace/")
        input("Log in to Facebook in the browser window (and set your Marketplace location/radius),\n"
              "then press Enter here to save the session... ")
        ctx.close()
