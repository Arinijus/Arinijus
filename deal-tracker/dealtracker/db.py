from __future__ import annotations

import sqlite3
import time

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    source        TEXT NOT NULL,
    item_id       TEXT NOT NULL,
    watch         TEXT NOT NULL,
    title         TEXT,
    price         REAL,
    currency      TEXT,
    url           TEXT,
    location      TEXT,
    relevant      INTEGER NOT NULL,
    first_seen    REAL NOT NULL,
    last_seen     REAL NOT NULL,
    alerted_price REAL,
    PRIMARY KEY (source, item_id, watch)
);
"""


class DB:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def count_for_watch(self, watch: str) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM listings WHERE watch = ?", (watch,)).fetchone()[0]

    def upsert(self, listing: Listing, watch: str, relevant: bool) -> None:
        now = time.time()
        self.conn.execute(
            """
            INSERT INTO listings (source, item_id, watch, title, price, currency, url, location,
                                  relevant, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source, item_id, watch) DO UPDATE SET
                title = excluded.title, price = excluded.price, url = excluded.url,
                location = excluded.location, relevant = excluded.relevant, last_seen = excluded.last_seen
            """,
            (listing.source, listing.item_id, watch, listing.title, listing.price, listing.currency,
             listing.url, listing.location, int(relevant), now, now),
        )
        self.conn.commit()

    def recent_prices(self, watch: str, days: int) -> list[float]:
        since = time.time() - days * 86400
        rows = self.conn.execute(
            "SELECT price FROM listings WHERE watch = ? AND relevant = 1 AND price IS NOT NULL AND last_seen >= ?",
            (watch, since),
        )
        return [r[0] for r in rows]

    def should_alert(self, listing: Listing, watch: str) -> bool:
        """Alert once per listing, and again only if the price drops another 5%+."""
        row = self.conn.execute(
            "SELECT alerted_price FROM listings WHERE source = ? AND item_id = ? AND watch = ?",
            (listing.source, listing.item_id, watch),
        ).fetchone()
        if row is None or row[0] is None:
            return True
        return listing.price is not None and listing.price <= row[0] * 0.95

    def mark_alerted(self, listing: Listing, watch: str) -> None:
        self.conn.execute(
            "UPDATE listings SET alerted_price = ? WHERE source = ? AND item_id = ? AND watch = ?",
            (listing.price, listing.source, listing.item_id, watch),
        )
        self.conn.commit()
