import unittest
from datetime import date

from research_daily_curve import daily_curves, daily_display, interpolate, label_position, polynomial_smooth
from seasonality import PriceSeries


class DailyCurveTests(unittest.TestCase):
    def test_polynomial_smoothing_preserves_cubic_including_edges(self):
        values = [index ** 3 - 2 * index ** 2 + 4 * index - 7 for index in range(21)]
        smoothed = polynomial_smooth(values)
        for actual, expected in zip(smoothed, values):
            self.assertAlmostEqual(actual, expected, places=8)

    def test_fractional_daily_win_is_interpolated_flag_not_cumulative_win(self):
        series = PriceSeries('UNSEEN', [date(2024, 1, 2), date(2024, 6, 3), date(2024, 12, 31)], [100, 90, 95])
        curves = daily_curves(series, date(2025, 10, 1), 1, 5)
        display = daily_display(curves, 5)
        self.assertAlmostEqual(display[3]['avg'], -7.5)
        self.assertEqual(display[3]['win_rate'], 50)
        self.assertEqual(display[4]['win_rate'], 100)
        self.assertEqual(display[4]['count'], 1)

    def test_current_year_and_partial_ipo_year_are_excluded(self):
        series = PriceSeries('UNSEEN', [date(2023, 5, 1), date(2023, 12, 29),
                             date(2024, 1, 2), date(2024, 12, 31),
                             date(2025, 1, 2), date(2025, 9, 30)], [100, 105, 100, 110, 100, 120])
        curves = daily_curves(series, date(2025, 10, 1), 2, 3)
        self.assertEqual(sorted(curves), [2024])
        self.assertAlmostEqual(curves[2024]['returns'][-1], .1)

    def test_label_floor_and_coordinate_rounding_are_explicit(self):
        self.assertEqual(label_position(250, 126), 124)
        self.assertEqual(label_position(250, 126, precision=2), 125)
        self.assertEqual(label_position(250, 251, precision=2), 249)
        self.assertEqual(interpolate([10, 20], 1, 3), 15)


if __name__ == '__main__':
    unittest.main()
