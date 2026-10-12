# Deal tracker: Vinted + Facebook Marketplace

This tool watches Vinted and Facebook Marketplace for tech you name, such as GPUs, consoles, phones and laptops. It pings you on Discord, Telegram or your phone (ntfy) when something is listed **well below what it usually sells for** near you.

## How it decides what a "steal" is

1. **Search.** On every scan, each watch searches its query on Vinted (your country's site) and on Marketplace (your city and radius), newest listings first.
2. **Junk filter.** It drops a listing if:
   - the title is missing a required word (so an RTX 3060 doesn't count as a 3070)
   - the title has a junk word: `broken`, `for parts`, `box only`, `icloud locked`, `wanted`, plus Lithuanian equivalents (edit these for your language)
   - the price is outside the watch's min/max window
3. **Market price.** Every relevant listing goes into a local SQLite database. The market price is the **median asking price over the last 45 days**. It needs at least 8 listings, and the first Vinted scan usually gives that. If you prefer, set `market_price` yourself.
4. **Steal.** A listing is a steal if its price is **≤ 65% of the market price** (`steal_ratio`). Anything under 15% (`min_ratio`) is ignored, because that's usually a scam, a broken item or an accessory. `target_price` is an extra rule: anything at or below it always alerts.
5. **Alerts.** You get one alert per listing. It alerts again only if the price drops by another 5% or more. The first scan of a new watch only builds the baseline and doesn't notify, so you don't get flooded with old listings.

## Setup

```bash
cd deal-tracker
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.toml config.toml                     # then edit it
```

In `config.toml`:

- **`[vinted] domain`**: your country's site (`www.vinted.lt`, `www.vinted.pl`, `www.vinted.co.uk`, …). Vinted ships nationwide, so "local" there means your country.
- **`[marketplace] location`**: open Marketplace in a browser, browse your area and copy the part after `/marketplace/` in the URL (for example `vilnius` or a long number). Set `radius_km` too.
- **`[notify]`**: fill in at least one. The easiest is a Discord webhook (Server Settings → Integrations → Webhooks). For phone push without an account, use [ntfy](https://ntfy.sh): install the app, subscribe to a long random topic name, and put `https://ntfy.sh/<that-topic>` in `ntfy_url`.
- **`[[watch]]`**: one block per thing you want. The example config includes RTX 3070/3080, PS5, Steam Deck, iPhone 14 Pro and MacBook M1/M2.

Check that notifications work:

```bash
python -m dealtracker test-notify
```

### Facebook Marketplace (optional)

Marketplace has no API and needs a login, so the tracker drives a real Chromium browser with your session:

```bash
playwright install chromium
python -m dealtracker fb-login     # a browser opens: log in, set your location/radius, press Enter
```

Then set `[marketplace] enabled = true`. The login is saved in `.fb-profile/`, which is git-ignored. Don't share that folder.

> ⚠️ Automated browsing is against Facebook's terms. Keep `interval` at 10 minutes or more and don't run many watches, or your account may get checkpointed. A spare account is a safer choice.

## Running it

```bash
python -m dealtracker run            # scans forever, every `interval` seconds
python -m dealtracker run --once     # one scan, for cron / Task Scheduler
python -m dealtracker stats          # market price per watch and the price that counts as a steal
```

To run it on a schedule with cron (Linux/macOS) or a Raspberry Pi, scanning every 10 minutes:

```
*/10 * * * * cd /path/to/deal-tracker && .venv/bin/python -m dealtracker run --once >> tracker.log 2>&1
```

On Windows, add a Task Scheduler task that runs `python -m dealtracker run` at logon.

## Tuning tips

- **Too many alerts?** Lower `steal_ratio` (try 0.55), add `exclude` words, or tighten `require`.
- **Missing deals?** Raise `steal_ratio` to 0.7–0.75. Keep the min/max window wide so the median isn't skewed.
- **Accessories getting through** (cases, cables, games)? Raise `min_price` above what accessories cost. That works better than excluding "case", which would also hide "PS5 + case + 2 games" bundles.
- **Same product in different variants** (Ti/Super, Pro/Pro Max, 8GB/16GB): make them separate watches and use `exclude` (for example `["ti"]` on a 3070 watch, `["max"]` on a 14 Pro watch). Otherwise their prices get mixed into one median.
- **Vinted returns 403s?** `pip install curl_cffi`, which is already in requirements. It makes the requests look like real Chrome.
- Run `stats` after a day or two to see whether the estimated market prices look right. If one doesn't, set `market_price` for that watch.

## Tests

```bash
python -m unittest -v
```
