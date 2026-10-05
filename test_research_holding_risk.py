import unittest

from research_holding_risk import select


class HoldingRiskTests(unittest.TestCase):
    def test_intrahold_filter_rejects_profitable_but_deep_loss_path(self):
        safe = {'entry_day': 7, 'win_rate': .8, 'avg_return': .02, 'worst_path_drawdown': -.05}
        deep_loss = {'entry_day': 14, 'win_rate': 1., 'avg_return': .08, 'worst_path_drawdown': -.20}
        rule = {'entry_step': 7, 'objective': 'win_mean', 'risk_field': 'worst_path_drawdown', 'risk_cap': .1}
        self.assertIs(select([safe, deep_loss], rule), safe)
        self.assertIs(select([safe, deep_loss], {**rule, 'risk_cap': None}), deep_loss)

    def test_risk_filter_does_not_insert_dates_outside_candidate_grid(self):
        excluded = {'entry_day': 8, 'win_rate': 1., 'avg_return': .08, 'worst_path_drawdown': -.01}
        rule = {'entry_step': 7, 'objective': 'win_mean', 'risk_field': 'worst_path_drawdown', 'risk_cap': .1}
        self.assertIsNone(select([excluded], rule))
