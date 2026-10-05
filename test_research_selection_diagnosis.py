from dataclasses import replace
from datetime import date
import unittest

from research_selection_diagnosis import classify, grid_rows, select_rows
from seasonality import Profile, PriceSeries, all_windows, evaluate_window


class SelectionDiagnosisTests(unittest.TestCase):
    def fixture(self, values, profile):
        dates = [date(2023, 1, 2), date(2023, 1, 3), date(2023, 1, 4),
                 date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
        series = PriceSeries('UNSEEN', dates, values)
        cutoff = date(2025, 1, 1)
        pool = all_windows(series, 1, cutoff, replace(profile, entry_step=1), 2)
        return series, cutoff, pool

    def test_holiday_alias_is_display_difference_not_absent_candidate(self):
        profile = Profile(entry_step=2, holds=(1,))
        series, cutoff, pool = self.fixture([100, 110, 111, 100, 110, 111], profile)
        fixed = evaluate_window(series, 1, 1, cutoff, profile, 2)
        grid = grid_rows(pool, profile)
        chosen = select_rows(grid, profile)
        self.assertEqual(chosen['entry_day'], 2)
        self.assertEqual(classify(fixed, fixed, chosen, grid, profile), 'display_only')

    def test_unavailable_economic_window_is_candidate_generation(self):
        profile = Profile(entry_step=4, holds=(1,))
        series, cutoff, pool = self.fixture([100, 110, 111, 100, 110, 111], profile)
        fixed = evaluate_window(series, 2, 1, cutoff, profile, 2)
        grid = grid_rows(pool, profile)
        self.assertEqual(classify(fixed, fixed, select_rows(grid, profile), grid, profile), 'candidate_generation')

    def test_better_score_is_ranking_and_exact_tie_is_separate(self):
        profile = Profile(holds=(1,))
        series, cutoff, pool = self.fixture([100, 101, 120, 100, 101, 120], profile)
        fixed = evaluate_window(series, 2, 1, cutoff, profile, 2)
        self.assertEqual(classify(fixed, fixed, select_rows(pool, profile), pool, profile), 'ranking')
        series, cutoff, pool = self.fixture([100] * 6, profile)
        fixed = evaluate_window(series, 3, 1, cutoff, profile, 2)
        self.assertEqual(classify(fixed, fixed, select_rows(pool, profile), pool, profile), 'tie_order')
