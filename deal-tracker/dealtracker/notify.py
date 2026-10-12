from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests

from .models import Listing, Watch
from .scoring import MarketEstimate, Verdict

log = logging.getLogger(__name__)


def format_message(listing: Listing, verdict: Verdict, watch: Watch, market: MarketEstimate) -> tuple[str, str]:
    title = f"STEAL [{watch.name}] {listing.price:g} {listing.currency} - {listing.title}"
    lines = [
        f"Source: {listing.source}" + (f" - {listing.location}" if listing.location else ""),
        f"Why: {verdict.reason}",
    ]
    if market.price:
        kind = "your price" if market.manual else f"median of {market.samples} listings"
        lines.append(f"Market: ~{market.price:.0f} {listing.currency} ({kind})")
    if listing.condition:
        lines.append(f"Condition: {listing.condition}")
    lines.append(listing.url)
    return title, "\n".join(lines)


class Notifier:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def send(self, title: str, body: str, url: str = "", image: str = "") -> None:
        c = self.cfg
        if c.get("console", True):
            print(f"\n=== {title}\n{body}\n", flush=True)
        if c.get("discord_webhook"):
            embed = {"title": title[:256], "description": body[:4000], "url": url or None, "color": 0x2ECC71}
            if image:
                embed["thumbnail"] = {"url": image}
            self._post(c["discord_webhook"], json={"embeds": [embed]})
        if c.get("telegram_bot_token") and c.get("telegram_chat_id"):
            self._post(f"https://api.telegram.org/bot{c['telegram_bot_token']}/sendMessage",
                       json={"chat_id": c["telegram_chat_id"], "text": f"{title}\n\n{body}"})
        if c.get("ntfy_url"):
            # Header values must be latin-1, so non-ASCII titles go in the body only.
            headers = {"Title": title.encode("latin-1", "replace").decode("latin-1"), "Tags": "moneybag"}
            if url:
                headers["Click"] = url
            self._post(c["ntfy_url"], data=body.encode(), headers=headers)

    @staticmethod
    def _post(url: str, **kwargs) -> None:
        try:
            r = requests.post(url, timeout=15, **kwargs)
            if r.status_code >= 400:
                log.warning("notification to %s failed: HTTP %s %s", urlparse(url).netloc, r.status_code, r.text[:200])
        except requests.RequestException as e:
            # Don't log the exception text: it contains the URL, which can contain a bot token.
            log.warning("notification to %s failed: %s", urlparse(url).netloc, type(e).__name__)
