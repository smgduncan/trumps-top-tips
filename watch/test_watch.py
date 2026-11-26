import datetime as dt
import unittest
from unittest.mock import patch

from watch import desk as watch


SAMPLE = b'''<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Truth</title><description>Nvidia is great, we made a great deal!</description>
<link>https://truthsocial.com/@realDonaldTrump/1</link><guid>1</guid>
<pubDate>Wed, 25 Nov 2026 15:00:00 GMT</pubDate></item>
<item><title>Truth</title><description>Unrelated lunch post</description>
<link>https://truthsocial.com/@realDonaldTrump/2</link><guid>2</guid>
<pubDate>Wed, 25 Nov 2026 15:00:00 GMT</pubDate></item>
</channel></rss>'''


class WatchTests(unittest.TestCase):
    def test_parse_and_classify(self):
        posts = watch.parse_feed(SAMPLE)
        self.assertEqual(len(posts), 2)
        self.assertIn("Nvidia", posts[0]["text"])
        hit = watch.classify(posts[0]["text"])
        self.assertEqual((hit["asset"], hit["direction"]), ("NVDA", "buy"))
        self.assertIsNone(watch.classify(posts[1]["text"]))

    def test_five_minute_rule(self):
        now = dt.datetime(2026, 11, 25, 15, 4, tzinfo=dt.timezone.utc)
        post = {"post_id": "1", "published": "Wed, 25 Nov 2026 15:00:00 GMT",
                "text": "Nvidia is great, great deal", "url": "https://example.com/1"}
        self.assertIsNone(watch.build_signal(post, now))
        later = watch.build_signal(post, now + dt.timedelta(minutes=2))
        self.assertIsNotNone(later)
        self.assertEqual(later["asset"], "NVDA")

    def test_session_helpers(self):
        self.assertFalse(watch.is_rth(dt.datetime(2026, 11, 25, 23, 0, tzinfo=dt.timezone.utc)))
        self.assertTrue(watch.is_rth(dt.datetime(2026, 11, 25, 15, 0, tzinfo=dt.timezone.utc)))
        nxt = watch.next_open(dt.datetime(2026, 11, 28, 10, 0, tzinfo=dt.timezone.utc))
        self.assertEqual(nxt.astimezone(watch.NY).weekday(), 0)

    def test_price_and_merge(self):
        series = [(dt.datetime(2026, 11, 25, 15, 0, tzinfo=dt.timezone.utc), 10.0),
                  (dt.datetime(2026, 11, 25, 15, 5, tzinfo=dt.timezone.utc), 11.0)]
        target = dt.datetime(2026, 11, 25, 15, 2, tzinfo=dt.timezone.utc)
        self.assertEqual(watch.price_at_or_after(series, target, series[-1][0]), 11.0)
        a = {"signal_id": "x", "status": "closed", "close_return_pct": 4.0}
        b = {"signal_id": "x", "status": "pending_price", "close_return_pct": None}
        self.assertEqual(watch.merge([a], [b]), [a])

    def test_build_signal_with_market_bars(self):
        post = {"post_id": "77", "published": "Wed, 25 Nov 2026 15:00:00 GMT",
                "text": "Intel is a great deal", "url": "https://example.com/77"}
        now = dt.datetime(2026, 11, 27, 21, 0, tzinfo=dt.timezone.utc)
        five = [(dt.datetime(2026, 11, 25, 15, 5, tzinfo=dt.timezone.utc), 20.0)]
        daily = [(dt.datetime(2026, 11, 25, 14, 30, tzinfo=dt.timezone.utc), 21.0),
                 (dt.datetime(2026, 11, 26, 14, 30, tzinfo=dt.timezone.utc), 22.0),
                 (dt.datetime(2026, 11, 27, 14, 30, tzinfo=dt.timezone.utc), 23.0)]
        with patch.object(watch, "bars", side_effect=lambda *a: five if a[1] == "5m" else daily):
            signal = watch.build_signal(post, now)
        self.assertEqual(signal["asset"], "INTC")
        self.assertEqual(signal["status"], "closed")
        self.assertEqual(signal["close_return_pct"], 5.0)
        self.assertEqual(signal["t2_return_pct"], 15.0)


if __name__ == "__main__":
    unittest.main()
