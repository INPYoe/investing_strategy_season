import unittest
from datetime import date
from seasonality import PriceSeries
from research_price_vintage import normalize_vintage


class VintageTests(unittest.TestCase):
    def test_adjusted_prefix_and_raw_tail_share_action_basis(self):
        series = PriceSeries('OTHER', [date(2025, 1, d) for d in (2, 3, 6, 7)], [90, 99, 100, 102])
        events = [{'ex_date': '2025-01-06', 'cash': 1}]
        quotes = [{'date': '2025-01-03', 'close': 100}]
        result, info = normalize_vintage(series, '2025-01-02', events, quotes, True)
        self.assertEqual(result.prices, [89.1, 99, 100, 102])
        self.assertEqual(len(info['replacements']), 1)
        self.assertEqual(series.prices, [90, 99, 100, 102])

    def test_requires_independent_factor_and_explicit_tail_policy(self):
        series = PriceSeries('S', [date(2025, 1, d) for d in (2, 3, 6)], [90, 99, 100])
        events = [{'ex_date': '2025-01-06', 'cash': 1}]
        with self.assertRaises(ValueError):
            normalize_vintage(series, '2025-01-02', events, [], True)
        with self.assertRaises(ValueError):
            normalize_vintage(series, '2025-01-02', events, [])
