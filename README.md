# Trump's Top Tips

A public research ledger asking one narrow question: **after a Donald Trump
statement becomes public, is there still a measurable market reaction?** It
does not claim to know what he or his circle traded first, and it is not
investment advice.

The site is a dependency-free static dashboard (`public/`). It reads three JSON
files and works on Vercel with `outputDirectory: public`.

## What is here

- `public/events.json` — the curated archive: 13 statements, 30 reactions, each
  with a source URL. Mirrors the local ClickHouse `market` database on m1pro.
- `public/watch.json` — the **observation desk** journal written by
  `watch/desk.py`. Paper observations only; no orders are placed.
- `public/history.json` — price-linked backfill written by
  `history/backfill.py`: daily closes for the asset versus a sector ETF over
  each curated window.
- `public/podium.svg`, `public/loupe.svg` — original cartoon illustrations.
- `.github/workflows/watch.yml` — scheduled tick that fetches a public Trump
  post archive, applies the pre-registered rule, and commits only `watch.json`.

## Next step 1 — scheduled paper watch

Feed: `https://trumpstruth.org/feed`, an independent archive of public Truth
Social posts. Truth Social's own Mastodon-style endpoints were returning 403
from the build machine during testing, and there is no supported public API;
the archive has unknown publication lag. That lag is a limitation, not a
signal.

Rule, fixed in code:

1. A post must be at least five minutes old and must name a tracked company.
2. Entry is the first 5-minute bar at/after publication + 5 minutes, or the
   next US regular-hours open if the post arrived outside the session.
3. The signal, thesis and entry basis are written before close and T+2 marks
   are calculated. Marks use daily closes and a sector ETF benchmark.
4. Completed marks are never replaced by a later pending re-fetch.
5. The workflow writes only `public/watch.json`; the dashboard cannot change
   the archive or the backfill.

Run locally:

```bash
python3 -m unittest discover -s watch -p 'test_*.py'
python3 watch/desk.py --dry-run   # fetch and print, no write
python3 watch/desk.py             # write public/watch.json
```

## Next step 2 — historical price backfill

```bash
python3 -m unittest discover -s history -p 'test_*.py'
python3 history/backfill.py
```

`history/backfill.py` fetches daily closes from Yahoo's public chart endpoint:
`https://query1.finance.yahoo.com/v8/finance/chart/<SYMBOL>?period1=...&period2=...&interval=1d`.
Baseline is the last close on or before the window start; end is the last
close on or before the window end. This handles weekends and holidays without
inventing an intraday fill. Rows where the Yahoo close series differs from the
curated reported move by more than 2 percentage points are flagged `⚠` and
`data_mismatch: true` — they are not silently reconciled.

## Caveats

- Daily closes are a proxy, not proof that a trade was available at that price.
- Sector ETF benchmarks (SOXX, XLY, ITA, XLK, MSOS, SPY) are comparators, not
  tradable recommendations.
- A reported move can include price discovery before the post. Several archive
  examples reversed within a day or two.
- The GitHub Actions job is a research experiment, not a trading bot: no
  brokerage keys, no real orders, no position sizing.

## Deployment

Vercel project is connected to this repository with `outputDirectory: public`.
Pushes to `main` build the static site. The local home-automation dashboard
still has its own `/trumps-top-tips` page, but this repository is the canonical
public version.
