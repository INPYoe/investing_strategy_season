import unittest

from research_stages import displayed_anchor, select
from seasonality import Profile


class StageResearchTests(unittest.TestCase):
    def test_selection_uses_nominal_grid_before_display_conversion(self):
        candidate = {"entry_day": 21, "hold_days": 5, "win_rate": 1, "avg_return": .02,
                     "samples": [{"entry": "2025-01-20"}, {"entry": "2024-01-20"}]}
        outside = {**candidate, "entry_day": 20, "avg_return": .03}
        selected = select([outside, candidate], Profile(entry_step=7))
        self.assertIs(selected, candidate)
        self.assertEqual(displayed_anchor(selected, "median_doy"), 20)

    def test_display_rules_distinguish_leap_day_coordinates(self):
        candidate = {"entry_day": 63, "samples": [{"entry": "2024-03-03"}]}
        self.assertEqual(displayed_anchor(candidate, "median_doy"), 63)
        self.assertEqual(displayed_anchor(candidate, "median_md"), 62)

    def test_invalid_display_rule_is_explicit(self):
        with self.assertRaises(ValueError):
            displayed_anchor({"entry_day": 7, "samples": [{"entry": "2025-01-07"}]}, "unknown")
