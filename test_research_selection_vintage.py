import unittest
from datetime import date

from research_selection_vintage import report_for_choice, selection_cutoff, selection_pools
from seasonality import PriceSeries, Profile


class SelectionVintageTests(unittest.TestCase):
    def test_reporting_cache_separates_cutoffs(self):
        dates = [date(2023, 1, 2), date(2023, 1, 3), date(2024, 1, 2), date(2024, 1, 3)]
        series = PriceSeries('UNSEEN', dates, [100, 110, 100, 90])
        choice = {'entry_day': 2, 'hold_days': 1}
        cache = {}
        before = report_for_choice(series, date(2024, 1, 3), 1, choice, cache)
        after = report_for_choice(series, date(2024, 1, 4), 1, choice, cache)
        self.assertEqual(before['sample_count'], 1)
        self.assertEqual(after['sample_count'], 2)

    def test_reporting_cache_separates_price_objects_with_same_source_hash(self):
        dates = [date(2023, 1, 2), date(2023, 1, 3)]
        original = PriceSeries('UNSEEN', dates, [100, 110], sha256='same-original-file')
        changed_basis = PriceSeries('UNSEEN', dates, [100, 120], sha256='same-original-file')
        choice = {'entry_day': 2, 'hold_days': 1}
        cache = {}
        first = report_for_choice(original, date(2024, 1, 1), 1, choice, cache)
        changed = report_for_choice(changed_basis, date(2024, 1, 1), 1, choice, cache)
        self.assertAlmostEqual(first['avg_return'], .1)
        self.assertAlmostEqual(changed['avg_return'], .2)

    def test_earlier_snapshot_cannot_observe_later_price_movements(self):
        dates = [date(2025, 1, 2), date(2025, 1, 3), date(2026, 1, 2), date(2026, 1, 5)]
        first = PriceSeries('UNSEEN', dates, [100, 110, 100, 120])
        later_changed = PriceSeries('UNSEEN', dates, [100, 110, 100, 50])
        profile = Profile(holds=(1,))
        cutoff = selection_cutoff(date(2026, 10, 1), 'year_start')
        original = selection_pools(first, cutoff, profile, 1)
        changed = selection_pools(later_changed, cutoff, profile, 1)
        self.assertEqual(original, changed)
        self.assertTrue(original[1])
        self.assertEqual(original[1][0][0]['samples'][0]['year'], 2025)


if __name__ == '__main__':
    unittest.main()
