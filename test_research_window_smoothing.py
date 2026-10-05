import unittest

from research_window_smoothing import window_stats


class WindowHistoryTests(unittest.TestCase):
    def test_latest_completed_can_include_current_year_unlike_calendar_history(self):
        samples = [{'year': year, 'exit': f'{year}-02-01', 'return': value}
                   for year, value in zip(range(2023, 2027), [-.5, .1, .1, .1])]
        row = {'asof_year': 2026, 'samples': samples}
        latest = window_stats(row, 'latest_completed', 3)
        past = window_stats(row, 'past_entry_years', 3)
        self.assertEqual([sample['year'] for sample in latest['samples']], [2024, 2025, 2026])
        self.assertEqual([sample['year'] for sample in past['samples']], [2023, 2024, 2025])
        self.assertAlmostEqual(latest['avg_return'], .1)
        self.assertAlmostEqual(past['avg_return'], -.1)
        self.assertEqual(len(row['samples']), 4)


if __name__ == '__main__':
    unittest.main()
