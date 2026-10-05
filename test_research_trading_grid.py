import unittest
from datetime import date
from seasonality import PriceSeries
from research_trading_grid import grid_position


class TradingGridTests(unittest.TestCase):
    def test_series_origin_survives_price_prefix_truncation(self):
        sessions = [date(2025, 1, d) for d in (2, 3, 6, 7, 8, 9, 10)]
        truncated = PriceSeries('S', sessions[2:], [100]*5)
        rule = ('series', 0, 5, 0)
        self.assertTrue(grid_position(truncated, sessions, {'entry_day': 9}, date(2025, 12, 1), rule, 10, sessions[0]))
        self.assertFalse(grid_position(truncated, sessions, {'entry_day': 9}, date(2025, 12, 1), rule, 10))

    def test_weekend_anchors_share_next_session_grid_position(self):
        sessions = [date(2025, 1, d) for d in (2, 3, 6, 7, 8)]
        series = PriceSeries('S', sessions, [100]*5)
        rule = ('month', 0, 5, 2)
        for day in (4, 5, 6):
            self.assertTrue(grid_position(series, sessions, {'entry_day': day}, date(2025, 12, 1), rule, 10))
