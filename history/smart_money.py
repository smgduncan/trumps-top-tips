#!/usr/bin/env python3
"""Smart money moves: observable volume/price activity BEFORE a public statement.

Nothing here identifies who traded or why. It measures public market activity
in the 5 minutes, 1 hour and prior session before a statement, then compares a
$1,000 notional before vs after the public entry proxy.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from .backfill import CHART, NY, UA, fetch_bars, statement_et_date
except ImportError:  # direct script execution
    from backfill import CHART, NY, UA, fetch_bars, statement_et_date

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "public" / "events.json"
OUT = ROOT / "public" / "smart.json"
SYMBOL_MAP = {"SPX": "^GSPC", "NDX": "^IXIC"}
FX_SYMBOLS = {"AUD": "AUDUSD=X", "GBP": "GBPUSD=X"}


def intraday(symbol: str, interval: str, period: str) -> list[dict]:
    url = f"{CHART}{urllib.parse.quote(symbol)}?range={period}&interval={interval}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        result = json.loads(r.read())["chart"]["result"][0]
    q = result["indicators"]["quote"][0]
    rows = []
    for t, o, c, v in zip(result["timestamp"], q["open"], q["close"], q["volume"]):
        if c is None:
            continue
        rows.append({"t": dt.datetime.fromtimestamp(t, dt.timezone.utc),
                     "open": float(o) if o is not None else float(c),
                     "close": float(c), "volume": int(v or 0)})
    return sorted(rows, key=lambda x: x["t"])


def published(moment: str) -> tuple[dt.datetime, bool]:
    d = dt.datetime.fromisoformat(moment.replace("Z", "+00:00"))
    if d.time() == dt.time(0, 0):
        # Date-only archive stamps: use the US open as a stated proxy.
        return dt.datetime.combine(d.date(), dt.time(14, 30), dt.timezone.utc), True
    return d.astimezone(dt.timezone.utc), False


def volume_before(bars: list[dict], at: dt.datetime, minutes: int) -> int:
    start = at - dt.timedelta(minutes=minutes)
    return sum(b["volume"] for b in bars if start <= b["t"] < at)


def price_before(bars: list[dict], at: dt.datetime) -> float | None:
    prior = [b for b in bars if b["t"] < at]
    return prior[-1]["close"] if prior else None


def price_after(bars: list[dict], at: dt.datetime) -> float | None:
    later = [b for b in bars if b["t"] >= at]
    return later[0]["close"] if later else None


def up_share(bars: list[dict], at: dt.datetime, minutes: int) -> float | None:
    window = [b for b in bars if at - dt.timedelta(minutes=minutes) <= b["t"] < at]
    total = sum(b["volume"] for b in window)
    if not total:
        return None
    return round(100 * sum(b["volume"] for b in window if b["close"] > b["open"]) / total, 1)


def build_rows(events: dict, intra=None, daily=None) -> list[dict]:
    intra = intra or (lambda sym, interval, period: intraday(sym, interval, period))
    daily = daily or fetch_bars
    statements = {s["statement_id"]: s for s in events["statements"]}
    grouped: dict[tuple[str, str], dict] = {}
    for reaction in events["reactions"]:
        key = (reaction["statement_id"], reaction["asset"])
        current = grouped.get(key)
        if current is None or (reaction.get("exit_price") is not None and current.get("exit_price") is None):
            grouped[key] = reaction
    rows = []
    for key, reaction in grouped.items():
        statement = statements.get(reaction["statement_id"], {})
        at, estimated = published(statement.get("stated_at", ""))
        asset = reaction["asset"]
        symbol = SYMBOL_MAP.get(asset, asset) or asset
        day = statement_et_date(statement.get("stated_at", "")) or at.date()
        try:
            m5 = intra(symbol, "5m", "60d") if (dt.datetime.now(dt.timezone.utc) - at).days <= 55 else []
            h1 = intra(symbol, "1h", "730d") if (dt.datetime.now(dt.timezone.utc) - at).days <= 700 else []
            d1 = daily(symbol, dt.datetime.combine(day - dt.timedelta(days=10), dt.time(), NY),
                       dt.datetime.combine(day + dt.timedelta(days=2), dt.time(), NY))
        except Exception:
            m5, h1, d1 = [], [], []

        fx = {}
        fx_cache = globals().setdefault("_fx_cache", {})
        for code, pair in FX_SYMBOLS.items():
            key = (pair, interval_key := ("5m" if m5 else "1h" if h1 else "1d"))
            if key not in fx_cache:
                try:
                    fx_cache[key] = intra(pair, "5m" if m5 else "1h", "60d" if m5 else "730d")
                except Exception:
                    fx_cache[key] = []
            series = fx_cache[key]
            before_rate = price_before(series, at)
            after_rate = price_after(series, at + dt.timedelta(minutes=5))
            fx[code] = {
                "before": before_rate, "after": after_rate,
                "move_pct": round((after_rate / before_rate - 1) * 100, 3) if before_rate and after_rate else None,
                "convert_1000_before": round(1000 * before_rate) if before_rate else None,
                "convert_1000_after": round(1000 * after_rate) if after_rate else None,
            }

        v5 = volume_before(m5, at, 5)
        v60 = volume_before(h1 or m5, at, 60)
        prior = [(d, c) for d, c, *_ in d1 if d < day]
        prior_volume = None
        if prior:
            # fetch_bars returns (date, close); volume needs a separate daily fetch below.
            prior_volume = None
        # Daily volume is fetched directly to keep the ratio meaningful.
        try:
            dv = _daily_volume(symbol, day, daily)
            prior_volume = dv
        except Exception:
            prior_volume = None

        typical5 = prior_volume / 78 if prior_volume else None
        typical60 = prior_volume / 6.5 if prior_volume else None
        p5 = price_before(m5 or h1, at)
        p60 = price_before(h1 or m5, at)
        pprev = prior[-1][1] if prior else None
        after = reaction.get("entry_price") or price_after(m5 or h1, at + dt.timedelta(minutes=5))
        exit_price = reaction.get("exit_price")
        if exit_price is None:
            end = reaction.get("window_end")
            if end:
                end_day = dt.datetime.fromisoformat(end.replace("Z", "+00:00")).date()
                matches = [c for d, c in d1 if d <= end_day]
                exit_price = matches[-1] if matches else None

        def value(price):
            return round(1000 * exit_price / price) if price and exit_price else None

        def short(price):
            return round(1000 * (1 - exit_price / price)) if price and exit_price else None

        ratio5 = round(v5 / typical5, 2) if v5 and typical5 else None
        ratio60 = round(v60 / typical60, 2) if v60 and typical60 else None
        score = None
        if ratio5 is not None or ratio60 is not None:
            score = min(100, round(max(0, ((ratio5 or 1) - 1) * 12) + max(0, ((ratio60 or 1) - 1) * 8)))
        rows.append({
            "statement_id": reaction["statement_id"], "reaction_id": reaction["reaction_id"],
            "headline": statement.get("headline", ""), "asset": asset,
            "published_at": statement.get("stated_at", ""), "time_estimated": estimated,
            "pre_5m_volume": v5 or None, "pre_1h_volume": v60 or None,
            "prior_day_volume": prior_volume,
            "pre_5m_vs_typical": ratio5, "pre_1h_vs_typical": ratio60,
            "pre_5m_move_pct": round((p5 / p60 - 1) * 100, 3) if p5 and p60 else None,
            "pre_1h_move_pct": round((p60 / pprev - 1) * 100, 3) if p60 and pprev else None,
            "pre_1h_up_volume_share": up_share(h1 or m5, at, 60),
            "price_t5": p5, "price_t60": p60, "price_prev_close": pprev,
            "price_after": after, "exit_price": exit_price,
            "buy_1000_before": value(p5), "buy_1000_after": value(after),
            "short_1000_before": short(p5), "short_1000_after": short(after),
            "smart_score": score,
            "audusd_before": fx["AUD"]["before"], "audusd_after": fx["AUD"]["after"],
            "audusd_move_pct": fx["AUD"]["move_pct"],
            "aud1000_to_usd_before": fx["AUD"]["convert_1000_before"],
            "aud1000_to_usd_after": fx["AUD"]["convert_1000_after"],
            "gbpusd_before": fx["GBP"]["before"], "gbpusd_after": fx["GBP"]["after"],
            "gbpusd_move_pct": fx["GBP"]["move_pct"],
            "gbp1000_to_usd_before": fx["GBP"]["convert_1000_before"],
            "gbp1000_to_usd_after": fx["GBP"]["convert_1000_after"],
            "source_url": reaction.get("source_url", ""),
            "note": "Public volume/price before a post. Not evidence of who traded or why.",
        })
    return rows


def _daily_volume(symbol: str, day: dt.date, daily) -> int | None:
    start = int(dt.datetime.combine(day - dt.timedelta(days=8), dt.time(), NY).timestamp())
    end = int(dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), NY).timestamp())
    url = f"{CHART}{urllib.parse.quote(symbol)}?period1={start}&period2={end}&interval=1d"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        result = json.loads(r.read())["chart"]["result"][0]
    stamps = result["timestamp"]
    vols = result["indicators"]["quote"][0]["volume"]
    pairs = [(dt.datetime.fromtimestamp(t, NY).date(), int(v or 0)) for t, v in zip(stamps, vols)]
    prior = [v for d, v in pairs if d < day]
    return prior[-1] if prior else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    rows = build_rows(json.loads(EVENTS.read_text()))
    result = {"as_of": dt.datetime.now(dt.timezone.utc).isoformat(),
              "method": "Yahoo public volume/price; 5m available ~55d, 1h ~700d, daily further back; no order-flow or trader identity",
              "rows": rows}
    if args.dry_run:
        print(json.dumps(result, indent=2)[:5000])
        return
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n")
    print(f"wrote {OUT}: {len(rows)} rows, as_of {result['as_of']}")


if __name__ == "__main__":
    main()
