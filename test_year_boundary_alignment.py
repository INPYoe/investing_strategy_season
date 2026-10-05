import unittest
from dataclasses import replace
from datetime import date,timedelta
from seasonality import Profile,PriceSeries,evaluate_window


class YearBoundaryTests(unittest.TestCase):
    def setUp(self):
        start,end=date(2015,1,1),date(2027,1,1)
        days=[start+timedelta(days=i) for i in range((end-start).days)]
        days=[d for d in days if d.weekday()<5]
        self.series=PriceSeries('UNSEEN',days,[100+i/100 for i in range(len(days))])
        self.profile=Profile(cross_year_alignment='leap_after_first_year')

    def test_only_leap_year_boundary_after_initial_year_changes(self):
        ordinary=evaluate_window(self.series,355,20,date(2026,10,1),Profile())
        aligned=evaluate_window(self.series,355,20,date(2026,10,1),self.profile)
        pairs=list(zip(ordinary['samples'],aligned['samples']))
        changed=[a['year'] for a,b in pairs if a['exit']!=b['exit']]
        self.assertEqual(changed,[2020,2024])
        for a,b in pairs:
            if a['year'] in changed:
                i=self.series.dates.index(date.fromisoformat(a['exit']))
                self.assertEqual(b['exit'],self.series.dates[i+1].isoformat())

    def test_same_year_windows_are_unchanged(self):
        self.assertEqual(evaluate_window(self.series,80,20,date(2026,10,1),self.profile),
                         evaluate_window(self.series,80,20,date(2026,10,1),Profile()))

    def test_investment_mode_retains_true_holding_session_count(self):
        self.assertEqual(evaluate_window(self.series,355,20,date(2026,10,1),self.profile,mode='investment'),
                         evaluate_window(self.series,355,20,date(2026,10,1),Profile(),mode='investment'))
