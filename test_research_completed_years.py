import unittest
from datetime import date
from research_completed_years import completed_stats


class CompletedYearTests(unittest.TestCase):
    def test_completed_range_keeps_exact_period_and_excludes_current_year(self):
        row = {'samples':[{'year':y,'exit':f'{y}-03-01','return':y/10000} for y in range(2015,2027)]}
        stats = completed_stats(row,date(2026,10,1),10)
        self.assertEqual([s['year'] for s in stats['samples']],list(range(2016,2026)))
        inclusive = completed_stats(row,date(2026,10,1),10,True)
        self.assertEqual(inclusive['samples'][0]['year'],2015)

    def test_exit_constraint_can_exclude_unfinished_year_boundary(self):
        row = {'samples':[{'year':2024,'exit':'2025-01-01','return':.01},
                          {'year':2025,'exit':'2026-01-01','return':.02}]}
        self.assertEqual(completed_stats(row,date(2026,10,1),10)['sample_count'],2)
        self.assertEqual(completed_stats(row,date(2026,10,1),10,require_exit=True)['sample_count'],1)
