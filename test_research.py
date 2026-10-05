import unittest
from dataclasses import replace
from datetime import date

from lab import comparison
from research import choose, rounding_bounds
from seasonality import PriceSeries, Profile


def row(day, avg, win=1):
    return {"entry_day": day, "hold_days": 5, "avg_return": avg,
            "win_rate": win, "median_return": avg, "worst_return": avg}


class ResearchTests(unittest.TestCase):
    def test_month_origin_is_distinct_from_year_origin(self):
        # February 1 is DOY 32; the year grid uses DOY 35 instead.
        pool = [row(32, .01), row(35, .02), row(39, .03)]
        profile = Profile(entry_step=7)
        self.assertEqual(choose(pool, profile)["entry_day"], 35)
        self.assertEqual(choose(pool, profile, "month")["entry_day"], 39)

    def test_refinement_cannot_jump_to_distant_daily_winner(self):
        pool = [row(21, .01), row(20, .02), row(15, .03)]
        profile = Profile(entry_step=7)
        self.assertEqual(choose(pool, profile, radius=1)["entry_day"], 20)
        self.assertEqual(choose(pool, replace(profile, entry_step=1))["entry_day"], 15)

    def test_selection_history_excludes_current_year_from_scoring(self):
        def samples(day, past, current):
            return {**row(day, (past+current)/2), "asof_year": 2026,
                    "samples": [{"year": 2025, "exit": "2025-02-01", "return": past},
                                {"year": 2026, "exit": "2026-02-01", "return": current}]}
        pool = [samples(21, .01, .8), samples(28, .02, .03)]
        self.assertEqual(choose(pool, Profile(entry_step=7))["entry_day"], 21)
        self.assertEqual(choose(pool, Profile(entry_step=7, selection_history="past_entry_years"))["entry_day"], 28)

    def test_price_rounding_interval_contains_true_ratio(self):
        series = PriceSeries("S", [date(2025, 1, 2), date(2025, 1, 3)], [100, 101])
        samples = [{"entry": "2025-01-02", "exit": "2025-01-03"}]
        low, high = rounding_bounds(series, samples)
        self.assertLess(low, 101.00004/99.99996-1)
        self.assertGreater(high, 101.00004/99.99996-1)
        self.assertLess(high-low, .000003)

    def test_display_match_does_not_relax_numerical_match(self):
        expected = {"month": 1, "entry_day": 21, "exit_day": 28, "hold_days": 5,
                    "avg_return": .0101, "win_rate": 1, "sample_count": 10}
        result = comparison(expected, {**expected, "avg_return": .0102})
        self.assertTrue(result["displayed_average_match"])
        self.assertFalse(result["checks"]["avg_return"])
        self.assertFalse(result["all_match"])
