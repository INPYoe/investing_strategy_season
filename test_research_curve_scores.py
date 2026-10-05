import unittest
from research_curve_scores import curve_score


class CurveScoreTests(unittest.TestCase):
    def test_curve_growth_is_distinct_from_mean_trade_return(self):
        row={'win_rate':1,'samples':[{'entry_price':10,'exit_price':12,'year_base':10},
                                   {'entry_price':100,'exit_price':110,'year_base':100}]}
        self.assertAlmostEqual(curve_score(row,'price_ratio',False),12/110)
        self.assertAlmostEqual(curve_score(row,'annual_pnl',False),.15)
        self.assertAlmostEqual(curve_score(row,'annual_ratio',False),.15)
