#!/usr/bin/env python3
"""Backfill price-linked examples from public Yahoo daily bars.

The script never invents a price. For each curated reaction with a usable date
window it fetches daily closes for the asset and a sector ETF, then reports
the asset move, sector move and excess. Daily closes are a reproducible proxy,
not proof of a fill at the quoted price.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "public" / "events.json"
OUT = ROOT / "public" / "history.json"
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
NY = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0 TrumpTopTips/1.0 (research; no trading)"}
BENCH = {
    "NVDA": "SOXX", "INTC": "SOXX", "ORCL": "SOXX", "ARM": "SOXX", "SFTBY": "SOXX",
    "AEO": "XLY", "TSLA": "XLY", "LMT": "ITA", "BA": "ITA", "PLTR": "ITA",
    "AAPL": "XLK", "DELL": "XLK", "TLRY": "MSOS", "CGC": "MSOS", "ACB": "MSOS",
    "CRON": "MSOS", "DJT": "SPY",
}


def fetch_bars(symbol: str, start: dt.datetime, end: dt.datetime) -> list[tuple[dt.date, float]]:
    p1 = int((start - dt.timedelta(days=7)).timestamp())
    p2 = int((end + dt.timedelta(days=7)).timestamp())
    url = f"{CHART}{urllib.parse.quote(symbol)}?period1={p1}&period2={p2}&interval=1d"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        result = json.loads(r.read())["chart"]["result"][0]
    bars = []
    for stamp, close in zip(result["timestamp"], result["indicators"]["quote"][0]["close"]):
        if close is None:
            continue
        day = dt.datetime.fromtimestamp(stamp, NY).date()
        bars.append((day, round(float(close), 4)))
    return sorted(set(bars))


def latest_bar(symbol: str) -> tuple[dt.date, float] | None:
    url = f"{CHART}{urllib.parse.quote(symbol)}?range=5d&interval=1d"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        result = json.loads(r.read())["chart"]["result"][0]
    pairs = [(dt.datetime.fromtimestamp(t, NY).date(), float(c))
             for t, c in zip(result["timestamp"], result["indicators"]["quote"][0]["close"])
             if c is not None]
    return sorted(pairs)[-1] if pairs else None


def window_return(series: list[tuple[dt.date, float]], start: dt.date, end: dt.date) -> tuple[float | None, float | None, float | None]:
    """Baseline is the last close on/before start; end is the last close on/before end.

    Using the prior close as baseline handles weekends, holidays and same-day
    windows without inventing an intraday fill.
    """
    before = [(day, close) for day, close in series if day <= start]
    after = [(day, close) for day, close in series if day <= end]
    if not before or not after or before[-1][0] == after[-1][0]:
        return None, None, None
    first, last = before[-1][1], after[-1][1]
    return first, last, round((last / first - 1) * 100, 2)


def statement_et_date(raw: str) -> dt.date | None:
    """Date-only UTC stamps carry the US calendar date in the UTC date field."""
    try:
        d = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if d.time() == dt.time(0, 0) and d.tzinfo is not None:
            return d.date()
        return d.astimezone(NY).date()
    except (ValueError, TypeError):
        return None


def inferred_window(statement: dict, reaction: dict) -> tuple[dt.date, dt.date] | None:
    day = statement_et_date(statement.get("stated_at", ""))
    if not day:
        return None
    horizon = reaction.get("horizon", "").lower()
    if any(k in horizon for k in ("event-window", "since reversal", "reported cumulative")):
        return None
    if any(k in horizon for k in ("next session", "next day", "sunday post")):
        return day, day + dt.timedelta(days=1)
    if any(k in horizon for k in ("same day", "report to close", "post-announcement",
                                  "tease to close", "tweet-day close", "close-to-close")):
        return day - dt.timedelta(days=1), day
    return None


def candidates(events: dict) -> list[dict]:
    ids = {s["statement_id"]: s for s in events["statements"]}
    out = []
    for reaction in events["reactions"]:
        asset = reaction["asset"]
        if asset not in BENCH or reaction.get("executable") is False:
            continue
        statement = ids.get(reaction["statement_id"], {})
        explicit = reaction.get("window_start") and reaction.get("window_end")
        if explicit:
            start = dt.datetime.fromisoformat(reaction["window_start"].replace("Z", "+00:00")).date()
            end = dt.datetime.fromisoformat(reaction["window_end"].replace("Z", "+00:00")).date()
            basis = "curated entry/exit window"
        else:
            pair = inferred_window(statement, reaction)
            if not pair:
                continue
            start, end = pair
            basis = "inferred from statement date and horizon"
        if end < start:
            continue
        out.append({"reaction": reaction, "statement": statement, "start": start,
                    "end": end, "basis": basis, "asset": asset, "benchmark": BENCH[asset]})
    return out


def build_rows(events: dict, fetch=fetch_bars, latest_fetch=None) -> list[dict]:
    items = candidates(events)
    # Fetch each symbol once across the full span of every window that uses it.
    ranges: dict[str, tuple[dt.date, dt.date]] = {}
    for item in items:
        for symbol in (item["asset"], item["benchmark"]):
            lo, hi = ranges.get(symbol, (item["start"], item["end"]))
            ranges[symbol] = (min(lo, item["start"]), max(hi, item["end"]))
    cache = {}
    for symbol, (lo, hi) in ranges.items():
        cache[symbol] = fetch(symbol, dt.datetime.combine(lo, dt.time(), NY),
                              dt.datetime.combine(hi, dt.time(), NY))
    latest = {}
    if latest_fetch:
        for symbol in ranges:
            try:
                latest[symbol] = latest_fetch(symbol)
            except Exception:
                latest[symbol] = None
    rows = []
    for item in items:
        a0, a1, asset_pct = window_return(cache[item["asset"]], item["start"], item["end"])
        b0, b1, bench_pct = window_return(cache[item["benchmark"]], item["start"], item["end"])
        if asset_pct is None or bench_pct is None:
            continue
        reaction, statement = item["reaction"], item["statement"]
        reported = reaction.get("return_pct")
        mismatch = reported is not None and abs(float(reported) - asset_pct) > 2
        note = "Daily closes are a price proxy; the curated event may report a different quoted entry."
        if mismatch:
            note += f' Yahoo close series ({asset_pct}%) differs from the curated {reported}% move; treat this row as unverified.'
        row = {
            "statement_id": reaction["statement_id"],
            "reaction_id": reaction["reaction_id"],
            "headline": statement.get("headline", ""),
            "published_at": statement.get("stated_at", ""),
            "asset": item["asset"], "benchmark": item["benchmark"],
            "horizon": reaction["horizon"],
            "window": f'{item["start"]} to {item["end"]}', "window_basis": item["basis"],
            "asset_start_close": a0, "asset_end_close": a1,
            "value_1000_at_end": round(1000 * a1 / a0) if a0 and a1 else None,
            "latest_close": None, "latest_date": None, "value_1000_now": None,
            "asset_return_pct": asset_pct,
            "curated_reported_pct": reported,
            "data_mismatch": mismatch,
            "benchmark_return_pct": bench_pct,
            "excess_return_pct": round(asset_pct - bench_pct, 2),
            "verdict": "outperformed sector" if asset_pct >= bench_pct else "lagged sector",
            "price_source": "Yahoo Finance chart API, daily closes",
            "source_url": reaction.get("source_url", ""),
            "note": note,
        }
        pair = latest.get(item["asset"])
        if pair and a0:
            latest_date, latest_close = pair
            row["latest_date"] = latest_date.isoformat()
            row["latest_close"] = round(latest_close, 4)
            row["value_1000_now"] = round(1000 * latest_close / a0)
        rows.append(row)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    rows = build_rows(json.loads(EVENTS.read_text()), latest_fetch=latest_bar)
    result = {"as_of": dt.datetime.now(dt.timezone.utc).isoformat(),
              "method": "daily closes, asset vs sector ETF over the curated window; no look-ahead; 'now' is the latest daily close at generation time",
              "rows": rows}
    if args.dry_run:
        print(json.dumps(result, indent=2)[:4000])
        return
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n")
    print(f"wrote {OUT}: {len(rows)} price-linked rows, as_of {result['as_of']}")


if __name__ == "__main__":
    main()
