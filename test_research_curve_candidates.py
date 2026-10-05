import unittest
from datetime import date

from research_curve_candidates import candidate_indexes, curve_anchors


class CurveCandidateTests(unittest.TestCase):
    def test_local_minimum_uses_neighboring_month_and_first_tie(self):
        anchors = [31, 32, 33, 34, 35]
        self.assertEqual(candidate_indexes([0, 1, 0, 0, 2], anchors, 2, 'local_min'), [2])
        self.assertEqual(candidate_indexes([0, 1, 0, 0, 2], anchors, 2, 'month_min'), [2])

    def test_calendar_mapping_does_not_implicitly_convert_leap_day_numbers(self):
        curves = {2024: {'dates': [date(2024, 1, 2), date(2024, 12, 31)]},
                  2025: {'dates': [date(2025, 1, 2), date(2025, 12, 31)]}}
        self.assertEqual(curve_anchors(curves, 'first_doy', None, 2), [2, None])
        self.assertEqual(curve_anchors(curves, 'median_md', None, 2), [2, 365])


if __name__ == '__main__':
    unittest.main()
