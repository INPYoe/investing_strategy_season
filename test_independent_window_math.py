from dataclasses import asdict
from datetime import date, timedelta
import unittest

from independent_window_math import calculate, path_metrics, signature
from seasonality import Profile, PriceSeries, evaluate_window


class IndependentWindowTests(unittest.TestCase):
    def test_exclusive_cutoff_and_latest_completed_observation(self):
        dates = [date(2023, 1, 3), date(2023, 1, 4), date(2024, 1, 2), date(2024, 1, 3)]
        prices = [100, 110, 100, 120]
        convention = asdict(Profile())
        previous = calculate(dates, prices, 'UNSEEN', 1, 1, date(2024, 1, 3), convention, 1)
        self.assertEqual(previous['sample_count'], 1)
        self.assertAlmostEqual(previous['avg_return'], .1)
        both = calculate(dates, prices, 'UNSEEN', 1, 1, date(2024, 1, 4), convention, 1)
        self.assertEqual(both['sample_count'], 2)
        self.assertAlmostEqual(both['avg_return'], .15)
        latest = calculate(dates, prices, 'UNSEEN', 1, 1, date(2024, 1, 4), convention, 1, 'investment')
        self.assertEqual(latest['sample_count'], 1)
        self.assertAlmostEqual(latest['avg_return'], .2)

    def test_leap_hypothesis_is_replica_only_and_excludes_initial_year(self):
        dates = [date(2019, 12, 31), date(2020, 1, 2), date(2020, 1, 3),
                 date(2020, 12, 30), date(2020, 12, 31), date(2021, 1, 4), date(2021, 1, 5)]
        prices = [100, 105, 110, 100, 101, 120, 130]
        convention = asdict(Profile(cross_year_alignment='leap_after_first_year'))
        replica = calculate(dates, prices, 'UNSEEN', 365, 2, date(2021, 2, 1), convention, 2)
        investment = calculate(dates, prices, 'UNSEEN', 365, 2, date(2021, 2, 1), convention, 2, 'investment')
        initial = calculate(dates, prices, 'UNSEEN', 365, 2, date(2021, 2, 1), convention, 1)
        self.assertAlmostEqual(replica['avg_return'], .2)
        self.assertAlmostEqual(investment['avg_return'], .15)
        self.assertEqual(initial['samples'][0]['exit'], '2021-01-04')

    def test_ipo_distance_and_price_scale_do_not_create_observations(self):
        dates = [date(2023, 3, 1), date(2023, 3, 2), date(2024, 1, 2), date(2024, 1, 3)]
        prices = [100, 90, 100, 110]
        convention = asdict(Profile())
        first = calculate(dates, prices, 'UNSEEN', 1, 1, date(2024, 2, 1), convention, 1)
        scaled = calculate(dates, [p * 10 for p in prices], 'UNSEEN', 1, 1, date(2024, 2, 1), convention, 1)
        self.assertEqual(first, scaled)
        self.assertEqual([s['year'] for s in first['samples']], [2024])
        self.assertIsNone(calculate(dates, prices, 'UNSEEN', 1, 1, date(2024, 2, 1), convention, 2, 'investment'))

    def test_path_drawdown_distinguishes_intrahold_loss_from_final_loss(self):
        dates = [date(2023, 1, 3), date(2023, 1, 4), date(2023, 1, 5)]
        prices = [100, 80, 110]
        row = calculate(dates, prices, 'UNSEEN', 3, 2, date(2024, 1, 1), asdict(Profile()), 1)
        path = path_metrics(dates, prices, row)
        self.assertAlmostEqual(row['worst_return'], .1)
        self.assertAlmostEqual(path['worst_path_drawdown'], -.2)
        self.assertAlmostEqual(path['worst_intrahold_from_entry'], -.2)

    def test_conventions_agree_on_unseen_synthetic_calendar(self):
        dates = [date(2019, 1, 1) + timedelta(days=i) for i in range(1520)]
        dates = [d for d in dates if d.weekday() < 5 and (d.month, d.day) != (1, 1)]
        prices = [100 + i * .02 + (i % 11) for i in range(len(dates))]
        series = PriceSeries('UNSEEN', dates, prices)
        for dm in ('doy', 'month_day'):
            for roll in ('next', 'previous'):
                for offset in (0, -1):
                    for alignment in ('sessions', 'leap_after_first_year'):
                        profile = Profile(date_mode=dm, roll=roll, hold_offset=offset,
                                          holds=(2, 5), cross_year_alignment=alignment)
                        for day in (1, 59, 60, 61, 180, 360, 365):
                            for hold in profile.holds:
                                for mode in ('replica', 'investment'):
                                    ref = calculate(dates, prices, 'UNSEEN', day, hold, date(2023, 2, 1),
                                                    asdict(profile), 2, mode)
                                    actual = evaluate_window(series, day, hold, date(2023, 2, 1), profile, 2, mode)
                                    self.assertEqual(signature(ref), signature(actual))
                                    if ref:
                                        self.assertEqual(ref['exit_day'], actual['exit_day'])
                                        for field in ('avg_return', 'median_return', 'win_rate', 'worst_return', 'std'):
                                            self.assertAlmostEqual(ref[field], actual[field], places=13)
