import datetime as dt
import unittest
from unittest.mock import patch

from history import smart_money


AT = dt.datetime(2026, 11, 16, 18, 25, tzinfo=dt.timezone.utc)


def bar(minutes, close, volume):
    return {"t": AT - dt.timedelta(minutes=minutes), "open": close - 0.5, "close": close, "volume": volume}


class SmartMoneyTests(unittest.TestCase):
    def test_volume_windows_and_scenarios(self):
        events = {
            "statements": [{"statement_id": "s", "headline": "Test", "stated_at": "2026-11-16T18:25:00Z"}],
            "reactions": [{"statement_id": "s", "reaction_id": "r", "asset": "FAKE",
                           "entry_price": 100.0, "exit_price": 110.0, "source_url": "https://example.com"}],
        }
        m5 = [bar(10, 99.0, 100), bar(5, 99.5, 200), bar(0, 100.0, 50)]
        h1 = [bar(60, 98.0, 1000), bar(30, 99.0, 500), bar(5, 99.5, 200)]
        daily = [(dt.date(2026, 11, 13), 90.0), (dt.date(2026, 11, 16), 100.0)]

        def fake_intra(symbol, interval, period):
            return m5 if interval == "5m" else h1

        with patch.object(smart_money, "_daily_volume", return_value=7800):
            rows = smart_money.build_rows(events, fake_intra,
                                          lambda symbol, start, end: daily)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["pre_5m_volume"], 200)
        self.assertEqual(row["pre_1h_volume"], 1700)
        self.assertEqual(row["pre_5m_vs_typical"], 2.0)
        self.assertEqual(row["buy_1000_before"], 1106)
        self.assertEqual(row["buy_1000_after"], 1100)
        self.assertEqual(row["short_1000_before"], -106)
        self.assertEqual(row["short_1000_after"], -100)
        self.assertFalse(row["time_estimated"])

    def test_date_only_uses_open_proxy(self):
        at, estimated = smart_money.published("2025-08-04T00:00:00Z")
        self.assertTrue(estimated)
        self.assertEqual((at.hour, at.minute), (14, 30))


if __name__ == "__main__":
    unittest.main()
