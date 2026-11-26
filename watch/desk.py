#!/usr/bin/env python3
"""Paper-observation desk for public Trump posts.

No orders are placed. A signal is recorded only after a post is at least five
minutes old, and prices are taken at or after that point (or at the next US
regular-hours open). Entries and T+2 marks are frozen in the journal so later
price moves cannot change the recorded thesis.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "public" / "watch.json"
FEED = "https://trumpstruth.org/feed"
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
NY = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0 TrumpTopTips/1.0 (research; no trading)"}

# Only explicit company/product mentions become candidate signals; generic
# policy language is deliberately ignored to avoid narrative-driven calls.
TARGETS = [
    (("nvidia", "jensen huang", "h20 chip", "blackwell"), "NVDA", "SOXX", "semi"),
    (("intel",), "INTC", "SOXX", "semi"),
    (("oracle", "openai", "stargate"), "ORCL", "SOXX", "ai infrastructure"),
    (("palantir",), "PLTR", "ITA", "defence tech"),
    (("lockheed", "f-35"), "LMT", "ITA", "defence"),
    (("boeing",), "BA", "ITA", "aerospace"),
    (("tesla",), "TSLA", "XLY", "consumer discretionary"),
    (("apple", "iphone"), "AAPL", "XLK", "technology"),
    (("dell",), "DELL", "XLK", "technology"),
    (("american eagle", "sydney sweeney"), "AEO", "XLY", "retail"),
    (("cannabis", "cbd", "marijuana"), "MSOS", "SPY", "cannabis"),
]
BULL = ("backing", "support", "great", "proud", "win", "best", "buy", "approve",
        "resume", "deal", "brilliant", "fantastic", "correct", "success")
BEAR = ("tariff", "ban", "stop", "cancel", "out of control", "resign", "fired",
        "investigat", "bad", "fake", "cheat", "threat", "penalt")


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


def parse_feed(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    out = []
    for item in root.findall("./channel/item"):
        raw = item.findtext("description", "")
        out.append({
            "post_id": (item.findtext("guid") or item.findtext("link") or "").strip(),
            "published": (item.findtext("pubDate") or "").strip(),
            "text": strip_html(f'{item.findtext("title", "")} {raw}'),
            "url": (item.findtext("link") or "").strip(),
        })
    return out


def classify(text: str) -> dict | None:
    low = text.lower()
    hit = next(((asset, bench, theme) for keys, asset, bench, theme in TARGETS
                if any(k in low for k in keys)), None)
    if not hit:
        return None
    asset, bench, theme = hit
    score = sum(w in low for w in BULL) - sum(w in low for w in BEAR)
    if score == 0:
        return None
    return {"asset": asset, "benchmark": bench, "theme": theme,
            "direction": "buy" if score > 0 else "avoid",
            "conviction": min(5, 1 + abs(score)), "sentiment_score": score}


def published_dt(raw: str) -> dt.datetime | None:
    try:
        d = parsedate_to_datetime(raw)
        return d.replace(tzinfo=dt.timezone.utc) if d.tzinfo is None else d.astimezone(dt.timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None


def is_rth(moment: dt.datetime) -> bool:
    local = moment.astimezone(NY)
    return local.weekday() < 5 and dt.time(9, 30) <= local.time() < dt.time(16, 0)


def next_open(moment: dt.datetime) -> dt.datetime:
    local = moment.astimezone(NY)
    day = local.date()
    if local.time() < dt.time(9, 30) and day.weekday() < 5:
        open_local = dt.datetime.combine(day, dt.time(9, 30), NY)
    else:
        day += dt.timedelta(days=1)
        while day.weekday() >= 5:
            day += dt.timedelta(days=1)
        open_local = dt.datetime.combine(day, dt.time(9, 30), NY)
    return open_local.astimezone(dt.timezone.utc)


def bars(symbol: str, interval: str, period: str) -> list[tuple[dt.datetime, float]]:
    url = f"{CHART}{urllib.parse.quote(symbol)}?range={period}&interval={interval}"
    data = json.loads(fetch(url))["chart"]["result"][0]
    stamps = data["timestamp"]
    closes = data["indicators"]["quote"][0]["close"]
    return [(dt.datetime.fromtimestamp(t, dt.timezone.utc), c)
            for t, c in zip(stamps, closes) if c is not None]


def price_at_or_after(series: list[tuple[dt.datetime, float]], target: dt.datetime,
                      now: dt.datetime) -> float | None:
    eligible = [(t, c) for t, c in series if t >= target and t <= now]
    return eligible[0][1] if eligible else None


def marks(symbol: str, entry: dt.datetime, now: dt.datetime) -> dict:
    daily = [(t, c) for t, c in bars(symbol, "1d", "1mo") if t <= now]
    same_day = next(((t, c) for t, c in daily if t.date() == entry.date()), None)
    if not same_day:
        return {}
    index = daily.index(same_day)
    t2 = daily[index + 2][1] if index + 2 < len(daily) else None
    return {"close": same_day[1], "t2": t2, "close_date": same_day[0].date().isoformat()}


def build_signal(post: dict, now: dt.datetime) -> dict | None:
    published = published_dt(post["published"])
    classified = classify(post["text"])
    if not published or not classified or published > now:
        return None
    eligible_at = published + dt.timedelta(minutes=5)
    if eligible_at > now:
        return None
    entry_target = eligible_at if is_rth(eligible_at) else next_open(published)
    signal_id = f'{post["post_id"]}-{classified["asset"]}'
    signal = {
        "signal_id": signal_id, "post_id": post["post_id"], "post_url": post["url"],
        "published_at": published.isoformat(), "observed_at": now.isoformat(),
        "headline": post["text"][:240], "direction": classified["direction"],
        "asset": classified["asset"], "benchmark": classified["benchmark"],
        "theme": classified["theme"], "conviction": classified["conviction"],
        "thesis": f'Public post classified {classified["direction"]} for {classified["theme"]}; quoted at/after t+5m or next open.',
        "entry_basis": "first 5-minute bar at/after t+5m" if is_rth(eligible_at) else "next regular-hours open proxy",
        "entry_target": entry_target.isoformat(), "entry_price": None,
        "close_return_pct": None, "t2_return_pct": None,
        "excess_close_pct": None, "excess_t2_pct": None,
        "status": "pending_price", "execution": "paper observation only",
    }
    try:
        entry = price_at_or_after(bars(signal["asset"], "5m", "5d"), entry_target, now)
        if entry is None:
            return signal
        signal["entry_price"] = round(entry, 4)
        asset_marks = marks(signal["asset"], entry_target, now)
        bench_marks = marks(signal["benchmark"], entry_target, now)
        if not asset_marks or not bench_marks or not asset_marks.get("close") or not bench_marks.get("close"):
            return signal
        close = round((asset_marks["close"] / entry - 1) * 100, 2)
        # Benchmark entry is the first 5-minute bar at/after the same target time.
        bench_entry_series = [(t, c) for t, c in bars(signal["benchmark"], "5m", "5d") if t <= now]
        bench_entry = price_at_or_after(bench_entry_series, entry_target, now)
        if bench_entry:
            bench_close = round((bench_marks["close"] / bench_entry - 1) * 100, 2)
            signal["excess_close_pct"] = round(close - bench_close, 2)
        signal["close_return_pct"] = close
        if asset_marks.get("t2") and bench_marks.get("t2") and bench_entry:
            t2 = round((asset_marks["t2"] / entry - 1) * 100, 2)
            b_t2 = round((bench_marks["t2"] / bench_entry - 1) * 100, 2)
            signal["t2_return_pct"] = t2
            signal["excess_t2_pct"] = round(t2 - b_t2, 2)
            signal["status"] = "closed"
        else:
            signal["status"] = "mark_pending"
    except Exception as exc:
        signal["status"] = "price_error"
        signal["note"] = f"{type(exc).__name__}: {exc}"
    return signal


def merge(existing: list[dict], incoming: list[dict]) -> list[dict]:
    by_id = {s["signal_id"]: s for s in existing}
    for signal in incoming:
        old = by_id.get(signal["signal_id"])
        # Never overwrite a completed mark with a pending re-fetch.
        if old and old.get("status") == "closed" and signal.get("status") != "closed":
            continue
        by_id[signal["signal_id"]] = signal
    return sorted(by_id.values(), key=lambda s: s.get("published_at", ""))[-200:]


def run(feed_xml: bytes | None = None, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    posts = parse_feed(feed_xml if feed_xml is not None else fetch(FEED))
    existing = json.loads(OUT.read_text()) if OUT.exists() else {"signals": []}
    signals = []
    for post in posts[:40]:
        try:
            signal = build_signal(post, now)
            if signal:
                signals.append(signal)
        except Exception:
            continue
    return {"as_of": now.isoformat(), "source": FEED,
            "signals": merge(existing.get("signals", []), signals)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="fetch and print without writing")
    args = ap.parse_args()
    result = run()
    if args.dry_run:
        print(json.dumps(result, indent=2)[:4000])
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n")
    print(f'wrote {OUT}: {len(result["signals"])} signals, as_of {result["as_of"]}')


if __name__ == "__main__":
    main()
