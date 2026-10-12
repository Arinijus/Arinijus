"""Vinted via its (unofficial) web JSON API — the same one the website itself calls."""
from __future__ import annotations

import logging
from datetime import datetime

from ..models import Listing, Watch

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")


class SourceError(RuntimeError):
    pass


def _make_session():
    # curl_cffi mimics a real Chrome TLS fingerprint, which gets past Vinted's bot
    # protection far more reliably. Plain requests works too, most of the time.
    try:
        from curl_cffi import requests as cffi_requests
        return cffi_requests.Session(impersonate="chrome")
    except ImportError:
        import requests
        s = requests.Session()
        s.headers["User-Agent"] = UA
        return s


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_item(item: dict, base_url: str, default_currency: str) -> Listing:
    price = item.get("price")
    if isinstance(price, dict):
        amount, currency = price.get("amount"), price.get("currency_code")
    else:
        amount, currency = price, item.get("currency")

    url = item.get("url") or f"{base_url}/items/{item['id']}"
    if url.startswith("/"):
        url = base_url + url

    photo = item.get("photo") or {}
    posted_at = (photo.get("high_resolution") or {}).get("timestamp")
    if isinstance(item.get("created_at_ts"), str):
        try:
            posted_at = datetime.fromisoformat(item["created_at_ts"]).timestamp()
        except ValueError:
            pass

    user = item.get("user") or {}
    return Listing(
        source="vinted",
        item_id=str(item["id"]),
        title=item.get("title") or "",
        price=_to_float(amount),
        currency=currency or default_currency,
        url=url,
        location=item.get("city") or user.get("city") or "",
        image=photo.get("url") or "",
        condition=item.get("status") or "",
        posted_at=_to_float(posted_at),
    )


class VintedSource:
    name = "vinted"

    def __init__(self, domain: str, currency: str = "EUR", per_page: int = 96):
        self.base_url = f"https://{domain}"
        self.currency = currency
        self.per_page = per_page
        self.session = _make_session()
        self._has_cookie = False

    def _refresh_cookie(self) -> None:
        # Visiting the homepage hands out the anonymous access_token_web cookie the API needs.
        self.session.cookies.clear()
        r = self.session.get(self.base_url + "/", timeout=30)
        if r.status_code >= 400:
            raise SourceError(f"Vinted homepage returned HTTP {r.status_code}")
        self._has_cookie = True

    def search(self, watch: Watch) -> list[Listing]:
        params = {
            "search_text": watch.query,
            "order": "newest_first",
            "per_page": self.per_page,
            "page": 1,
            "currency": self.currency,
        }
        if watch.min_price is not None:
            params["price_from"] = watch.min_price
        if watch.max_price is not None:
            params["price_to"] = watch.max_price
        params.update(watch.vinted_params)

        for _ in range(2):
            if not self._has_cookie:
                self._refresh_cookie()
            r = self.session.get(
                self.base_url + "/api/v2/catalog/items",
                params=params,
                headers={"Accept": "application/json, text/plain, */*", "Referer": self.base_url + "/"},
                timeout=30,
            )
            if r.status_code in (401, 403):
                log.info("Vinted session expired, refreshing cookie")
                self._has_cookie = False
                continue
            if r.status_code == 429:
                raise SourceError("Vinted rate limit hit (HTTP 429) - increase the interval")
            if r.status_code >= 400:
                raise SourceError(f"Vinted API returned HTTP {r.status_code}")
            items = r.json().get("items") or []
            return [parse_item(i, self.base_url, self.currency) for i in items]
        raise SourceError("Vinted keeps rejecting the session (try `pip install curl_cffi`)")

    def close(self) -> None:
        self.session.close()
