import datetime as dt
import unittest

from history import backfill


class HistoryTests(unittest.TestCase):
    def test_window_return(self):
        series = [(dt.date(2026, 11, 16), 100.0), (dt.date(2026, 11, 20), 125.0),
                  (dt.date(2026, 11, 23), 165.0)]
        first, last, pct = backfill.window_return(series, dt.date(2026, 11, 16), dt.date(2026, 11, 20))
        self.assertEqual((first, last, pct), (100.0, 125.0, 25.0))

    def test_build_rows_with_fake_prices(self):
        events = {
            "statements": [{"statement_id": "s1", "headline": "Huang", "stated_at": "2026-11-16T18:25:00Z"}],
            "reactions": [{"statement_id": "s1", "reaction_id": "r1", "asset": "NVDA",
                           "horizon": "t+5", "window_start": "2026-11-16T21:00:00Z",
                           "window_end": "2026-11-23T21:00:00Z", "source_url": "https://example.com"}],
        }
        def fake(symbol, start, end):
            if symbol == "NVDA":
                return [(dt.date(2026, 11, 16), 100.0), (dt.date(2026, 11, 23), 110.0)]
            return [(dt.date(2026, 11, 16), 200.0), (dt.date(2026, 11, 23), 208.0)]
        rows = backfill.build_rows(events, fake)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["asset_return_pct"], 10.0)
        self.assertEqual(rows[0]["benchmark_return_pct"], 4.0)
        self.assertEqual(rows[0]["excess_return_pct"], 6.0)
        self.assertEqual(rows[0]["verdict"], "outperformed sector")


if __name__ == "__main__":
    unittest.main()
