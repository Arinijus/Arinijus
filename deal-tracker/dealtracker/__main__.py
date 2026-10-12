"""Scan Vinted and Facebook Marketplace for tech listings priced far below market."""
from __future__ import annotations

import argparse
import logging
import random
import statistics
import time

from . import config as config_mod
from .db import DB
from .notify import Notifier, format_message
from .scoring import classify, estimate_market, is_relevant
from .sources.vinted import SourceError, VintedSource

log = logging.getLogger("dealtracker")
FB_PROFILE_DIR = ".fb-profile"


def build_sources(cfg) -> dict:
    sources = {}
    if cfg.vinted.get("enabled", True):
        sources["vinted"] = VintedSource(cfg.vinted.get("domain", "www.vinted.lt"), cfg.vinted.get("currency", "EUR"))
    mp = cfg.marketplace
    if mp.get("enabled", False):
        from .sources.marketplace import MarketplaceSource
        sources["marketplace"] = MarketplaceSource(
            location=mp["location"],
            profile_dir=mp.get("profile_dir", FB_PROFILE_DIR),
            currency=mp.get("currency", "EUR"),
            radius_km=mp.get("radius_km"),
            days_since_listed=mp.get("days_since_listed", 1),
            headless=mp.get("headless", True),
        )
    return sources


def run_cycle(cfg, db: DB, sources: dict, notifier: Notifier) -> int:
    alerts = 0
    for watch in cfg.watches:
        first_run = db.count_for_watch(watch.name) == 0
        listings = []
        for name in watch.sources:
            source = sources.get(name)
            if not source:
                continue
            try:
                found = source.search(watch)
                log.info("[%s] %s: %d listings", watch.name, name, len(found))
                listings += found
            except SourceError as e:
                log.warning("[%s] %s: %s", watch.name, name, e)
            except Exception as e:  # network errors etc. - keep looping, try again next cycle
                log.warning("[%s] %s failed: %s: %s", watch.name, name, type(e).__name__, str(e)[:200])
                log.debug("traceback", exc_info=True)
            time.sleep(random.uniform(2, 5))  # be polite between requests

        relevant = []
        for listing in listings:
            ok, _ = is_relevant(listing, watch)
            db.upsert(listing, watch.name, ok)
            if ok:
                relevant.append(listing)

        market = estimate_market(db.recent_prices(watch.name, watch.history_days), watch)
        for listing in relevant:
            verdict = classify(listing, watch, market)
            if not verdict.is_steal or not db.should_alert(listing, watch.name):
                continue
            db.mark_alerted(listing, watch.name)
            if first_run:
                # Don't spam on the very first scan - those listings may be days old.
                log.info("[%s] existing deal (not notified): %s %s %s",
                         watch.name, listing.price, listing.title, listing.url)
                continue
            title, body = format_message(listing, verdict, watch, market)
            notifier.send(title, body, listing.url, listing.image)
            alerts += 1
        if first_run:
            log.info("[%s] first scan done - baseline built from %d listings; alerts start next cycle",
                     watch.name, len(relevant))
    return alerts


def cmd_run(cfg, once: bool) -> None:
    db = DB(cfg.db_path)
    notifier = Notifier(cfg.notify)
    sources = build_sources(cfg)
    if not sources:
        raise SystemExit("No sources enabled in config.")
    try:
        while True:
            start = time.time()
            n = run_cycle(cfg, db, sources, notifier)
            log.info("cycle done in %.0fs, %d new steal(s)", time.time() - start, n)
            if once:
                break
            # Jitter so requests don't land at robotic fixed intervals.
            time.sleep(cfg.interval * random.uniform(0.85, 1.15))
    except KeyboardInterrupt:
        pass
    finally:
        for s in sources.values():
            s.close()


def cmd_stats(cfg) -> None:
    db = DB(cfg.db_path)
    for watch in cfg.watches:
        prices = db.recent_prices(watch.name, watch.history_days)
        market = estimate_market(prices, watch)
        print(f"\n{watch.name}  (query: {watch.query!r})")
        print(f"  relevant listings, last {watch.history_days}d: {len(prices)}")
        if prices:
            q = statistics.quantiles(prices, n=4) if len(prices) >= 2 else [prices[0]] * 3
            print(f"  low / 25% / median / 75% / high: {min(prices):.0f} / {q[0]:.0f} / {q[1]:.0f} / {q[2]:.0f} / {max(prices):.0f}")
        if market.price:
            src = "manual" if market.manual else "auto"
            print(f"  market price ({src}): {market.price:.0f}  ->  steal at <= {market.price * watch.steal_ratio:.0f}")
        else:
            print(f"  market price: not enough data ({len(prices)}/{watch.min_samples})")
        if watch.target_price is not None:
            print(f"  target price: {watch.target_price:g}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="dealtracker", description=__doc__)
    parser.add_argument("-c", "--config", default="config.toml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="scan for deals (loops forever unless --once)")
    run.add_argument("--once", action="store_true", help="single scan, e.g. for cron")
    sub.add_parser("stats", help="show market price estimates per watch")
    sub.add_parser("test-notify", help="send a test notification")
    sub.add_parser("fb-login", help="log in to Facebook once so Marketplace can be scanned")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    if args.cmd == "fb-login":
        from .sources.marketplace import interactive_login
        try:
            profile = config_mod.load(args.config).marketplace.get("profile_dir", FB_PROFILE_DIR)
        except FileNotFoundError:
            profile = FB_PROFILE_DIR
        interactive_login(profile)
        return

    cfg = config_mod.load(args.config)
    if args.cmd == "run":
        cmd_run(cfg, args.once)
    elif args.cmd == "stats":
        cmd_stats(cfg)
    elif args.cmd == "test-notify":
        Notifier(cfg.notify).send("Deal tracker test", "If you can read this, notifications work.")


if __name__ == "__main__":
    main()
