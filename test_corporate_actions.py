import unittest
from datetime import date

from corporate_actions import delivery_sessions, infer_ex_date, reconstruct_close
from seasonality import PriceSeries
from research_dividends import stock_close


class CorporateActionTests(unittest.TestCase):
    def test_reverse_dividend_preserves_ex_date_price(self):
        series = PriceSeries("S", [date(2025, 1, 2), date(2025, 1, 3)], [98, 100])
        result = reconstruct_close(series, [{"ex_date": "2025-01-03", "cash_per_price_share": 1}])
        self.assertAlmostEqual(result.prices[0], 99)
        self.assertEqual(result.prices[1], 100)

    def test_terminal_factor_is_independent_scale_anchor(self):
        series = PriceSeries("S", [date(2025, 1, 2), date(2025, 1, 3)], [49, 50])
        result = reconstruct_close(series, [{"ex_date": "2025-01-03", "cash_per_price_share": 1}], .5)
        self.assertAlmostEqual(result.prices[0], 99)
        self.assertEqual(result.prices[1], 100)

    def test_non_delivery_record_date_rolls_before_cycle(self):
        sessions = [date(2024, 11, d) for d in (7, 8, 11, 12)]
        self.assertEqual(infer_ex_date(date(2024, 11, 11), delivery_sessions(sessions)), date(2024, 11, 8))

    def test_saturday_bank_holiday_does_not_remove_friday(self):
        self.assertIn(date(2023, 11, 10), delivery_sessions([date(2023, 11, 10)]))

    def test_unverified_tail_requires_explicit_hypothesis(self):
        series = PriceSeries("S", [date(2025, 1, d) for d in (2, 3, 6)], [98, 100, 102])
        external = PriceSeries("S", series.dates[:2], [99, 100])
        events = [{"ex_date": "2025-01-03", "cash_per_price_share": 1}]
        with self.assertRaisesRegex(ValueError, "Unverified website tail"):
            stock_close(series, events, external, date(2025, 1, 1))

    def test_external_anchor_reconstruction_is_target_free(self):
        series = PriceSeries("S", [date(2025, 1, d) for d in (2, 3, 6)], [98, 100, 102])
        external = PriceSeries("S", series.dates[:2], [99, 100])
        events = [{"ex_date": "2025-01-03", "cash_per_price_share": 1}]
        result, diagnostic = stock_close(series, events, external, date(2025, 1, 1), True)
        self.assertAlmostEqual(result.prices[0], 99)
        self.assertEqual(result.prices[1:], [100, 102])
        self.assertEqual(diagnostic["tail_policy"], "assumed raw")
        self.assertFalse(diagnostic["full_independent_price_validation"])
