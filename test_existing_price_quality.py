from datetime import date
import unittest

from audit_existing_prices import inspect_rows


class ExistingPriceQualityTests(unittest.TestCase):
    def test_ohlc_conflict_and_missing_adjusted_close_are_preserved_as_flags(self):
        rows = [{'date': '2024-01-02', 'open': 110, 'high': 105, 'low': 99, 'close': 100},
                {'date': '2024-01-03', 'open': 100, 'high': 101, 'low': 99, 'close': 101}]
        result = inspect_rows(rows, list(rows[0]), [date(2024, 1, 2), date(2024, 1, 3)],
                              date(2024, 1, 2), date(2024, 1, 4))
        self.assertEqual([x['kind'] for x in result['quality_failures']], ['invalid_ohlc'])
        self.assertFalse(result['has_adjusted_close_column'])
        self.assertFalse(result['inferred_adjusted_close_values'])
        self.assertEqual(result['close_values']['2024-01-02'], 100)
        self.assertEqual(rows[0]['open'], 110)

    def test_internal_gap_and_short_history_are_different_quality_findings(self):
        rows = [{'date': '2024-01-03', 'close': 100}, {'date': '2024-01-05', 'close': 101}]
        sessions = [date(2024, 1, x) for x in (2, 3, 4, 5)]
        result = inspect_rows(rows, list(rows[0]), sessions, date(2024, 1, 2), date(2024, 1, 6))
        self.assertEqual(result['within_file_missing_sessions'], ['2024-01-04'])
        self.assertEqual(result['requested_missing_session_count'], 2)
        self.assertFalse(result['covers_requested_sessions'])
