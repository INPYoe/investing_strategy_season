import unittest
from research_scores import choose, score
from seasonality import Profile


class ScoreTests(unittest.TestCase):
    def test_weighted_score_can_trade_win_probability_for_return(self):
        pool = [{'entry_day': 7, 'avg_return': .01, 'win_rate': 1},
                {'entry_day': 14, 'avg_return': .04, 'win_rate': .9}]
        self.assertEqual(choose(pool, Profile(entry_step=7), ('weighted_mean', 10))['entry_day'], 14)
        self.assertEqual(choose(pool, Profile(entry_step=7), ('weighted_mean', 20))['entry_day'], 7)

    def test_geometric_rule_penalizes_large_losses(self):
        volatile = {'avg_return': .05, 'win_rate': .5, 'samples': [{'return': .5}, {'return': -.4}]}
        steady = {'avg_return': .04, 'win_rate': 1, 'samples': [{'return': .04}, {'return': .04}]}
        self.assertGreater(score(volatile, ('mean_win', 0)), score(steady, ('mean_win', 0)))
        self.assertLess(score(volatile, ('geometric', 0)), score(steady, ('geometric', 0)))
