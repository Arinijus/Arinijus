import os
import tempfile
import unittest
from unittest import mock

from dealtracker import config as config_mod
from dealtracker.__main__ import run_cycle
from dealtracker.db import DB
from dealtracker.models import Listing, Watch
from dealtracker.scoring import classify, estimate_market, is_relevant
from dealtracker.sources.marketplace import parse_card, parse_price, search_url
from dealtracker.sources.vinted import parse_item

HERE = os.path.dirname(__file__)


def listing(title="RTX 3070 Founders Edition", price=300.0, item_id="1"):
    return Listing("vinted", item_id, title, price, "EUR", f"https://x/{item_id}")


class ScoringTest(unittest.TestCase):
    def setUp(self):
        self.watch = Watch(name="3070", query="rtx 3070", require=["3070"], exclude=["broken", "ti", "for parts"],
                           min_price=50, max_price=600)

    def test_relevance(self):
        self.assertTrue(is_relevant(listing(), self.watch)[0])
        self.assertFalse(is_relevant(listing("RTX 3060 12GB"), self.watch)[0])
        self.assertFalse(is_relevant(listing("RTX 3070 Ti"), self.watch)[0])
        self.assertFalse(is_relevant(listing("RTX 3070 for parts"), self.watch)[0])
        self.assertFalse(is_relevant(listing(price=20), self.watch)[0])
        self.assertFalse(is_relevant(listing(price=None), self.watch)[0])
        # whole-word only: "ti" must not match inside "Gaming" etc.
        self.assertTrue(is_relevant(listing("RTX 3070 Gaming OC tikrai veikia"), self.watch)[0])

    def test_steal_classification(self):
        market = estimate_market([300, 310, 290, 320, 280, 305, 295, 900], self.watch)
        self.assertAlmostEqual(market.price, 302.5)
        self.assertTrue(classify(listing(price=180), self.watch, market).is_steal)
        self.assertFalse(classify(listing(price=250), self.watch, market).is_steal)
        self.assertFalse(classify(listing(price=30), self.watch, market).is_steal)  # too good to be true

    def test_needs_samples_unless_target_or_manual(self):
        few = estimate_market([300, 310], self.watch)
        self.assertIsNone(few.price)
        self.assertFalse(classify(listing(price=100), self.watch, few).is_steal)
        self.watch.target_price = 150
        self.assertTrue(classify(listing(price=140), self.watch, few).is_steal)
        self.watch.target_price = None
        self.watch.market_price = 300
        self.assertTrue(classify(listing(price=150), self.watch, estimate_market([], self.watch)).is_steal)


class VintedParseTest(unittest.TestCase):
    def test_new_and_old_price_formats(self):
        new = parse_item({"id": 5, "title": "PS5", "price": {"amount": "250.0", "currency_code": "EUR"},
                          "url": "https://www.vinted.lt/items/5-ps5", "status": "Very good",
                          "photo": {"url": "https://img/5.jpg", "high_resolution": {"timestamp": 1760000000}}},
                         "https://www.vinted.lt", "EUR")
        self.assertEqual((new.price, new.currency, new.item_id, new.posted_at), (250.0, "EUR", "5", 1760000000.0))
        self.assertEqual(new.condition, "Very good")
        old = parse_item({"id": 6, "title": "PS5", "price": "199.9", "currency": "PLN", "url": "/items/6"},
                         "https://www.vinted.pl", "PLN")
        self.assertEqual((old.price, old.url), (199.9, "https://www.vinted.pl/items/6"))


class MarketplaceParseTest(unittest.TestCase):
    def test_parse_price(self):
        cases = {"€1,200": 1200, "1 200 €": 1200, "1.200,50 zł": 1200.5, "€12,50": 12.5, "$350": 350,
                 "£1,050.99": 1050.99, "Free": 0, "Nemokamai": 0, "1 500 €": 1500, "€1.200.000": 1200000}
        for text, expected in cases.items():
            self.assertAlmostEqual(parse_price(text), expected, msg=text)
        self.assertIsNone(parse_price("no price"))

    def test_parse_card(self):
        card = parse_card("/marketplace/item/123456789/?ref=search", "€150€220\nRTX 3070 Gaming X\nVilnius, Lithuania", "EUR")
        self.assertEqual((card.item_id, card.price, card.title, card.location),
                         ("123456789", 150.0, "RTX 3070 Gaming X", "Vilnius, Lithuania"))
        card = parse_card("/marketplace/item/42/", "€150\n€220\nSteam Deck 512GB\nKaunas", "EUR")
        self.assertEqual((card.price, card.title, card.location), (150.0, "Steam Deck 512GB", "Kaunas"))
        self.assertIsNone(parse_card("/marketplace/category/", "x", "EUR"))

    def test_search_url(self):
        url = search_url("vilnius", Watch(name="x", query="rtx 3070", min_price=50, max_price=400), 40, 1)
        self.assertTrue(url.startswith("https://www.facebook.com/marketplace/vilnius/search?query=rtx+3070"))
        self.assertIn("maxPrice=400", url)
        self.assertIn("radius=40", url)


class FakeSource:
    def __init__(self, batches):
        self.batches = batches

    def search(self, watch):
        return self.batches.pop(0)

    def close(self):
        pass


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, title, body, url="", image=""):
        self.sent.append(title)


class EndToEndTest(unittest.TestCase):
    def test_example_config_loads(self):
        cfg = config_mod.load(os.path.join(HERE, "..", "config.example.toml"))
        self.assertTrue(cfg.watches)
        w = cfg.watches[0]
        self.assertIn("broken", w.exclude)          # defaults merged in
        self.assertIn("laptop", w.exclude)          # plus per-watch
        self.assertEqual(w.steal_ratio, 0.65)

    @mock.patch("dealtracker.__main__.time.sleep")  # skip politeness delays
    def test_first_run_seeds_then_alerts_once(self, _sleep):
        watch = Watch(name="3070", query="rtx 3070", require=["3070"], min_samples=5)
        normal = [listing(price=p, item_id=str(i)) for i, p in enumerate([300, 310, 290, 320, 280, 305])]
        cheap_old = listing(price=150, item_id="old")
        cheap_new = listing(price=160, item_id="new")
        source = FakeSource([normal + [cheap_old], normal + [cheap_old, cheap_new], normal + [cheap_new]])

        class Cfg:
            watches = [watch]

        with tempfile.TemporaryDirectory() as d:
            db = DB(os.path.join(d, "t.db"))
            notifier = FakeNotifier()
            self.assertEqual(run_cycle(Cfg, db, {"vinted": source}, notifier), 0)  # baseline, no spam
            self.assertEqual(run_cycle(Cfg, db, {"vinted": source}, notifier), 1)  # only the new steal
            self.assertEqual(run_cycle(Cfg, db, {"vinted": source}, notifier), 0)  # no repeat
            self.assertIn("160", notifier.sent[0])


if __name__ == "__main__":
    unittest.main()
