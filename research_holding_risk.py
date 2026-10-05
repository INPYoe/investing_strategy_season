"""Test new holding-path risk constraints on frozen candidate metrics, offline.

The website's risk criteria are unknown. These are explicit global hypotheses,
not the investment-mode -10% final-return rule. Reference rows never enter a
candidate selector; they only score the training/diagnostic comparisons.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path

from lab import comparison
from research import counts, training_key
from seasonality import write_json


def score(row, name):
    if name == 'win_mean':
        return row['win_rate'], row['avg_return']
    if name == 'win_median':
        return row['win_rate'], row['median_return']
    if name == 'mean':
        return row['avg_return'],
    raise ValueError('Unknown score')


def select(pool, rule):
    eligible = [row for row in pool if row['entry_day'] % rule['entry_step'] == 0]
    if rule['risk_cap'] is not None:
        eligible = [row for row in eligible if row[rule['risk_field']] >= -rule['risk_cap']]
    return max(eligible, key=lambda row: score(row, rule['objective'])) if eligible else None


def dominant_rows(pool, target, target_path):
    years = [s['year'] for s in target['fixed_trade_samples']]
    fixed = target['fixed_window']
    base = [x for x in pool if x['sample_years'] == years and x['win_rate'] >= fixed['win_rate']
            and x['avg_return'] >= fixed['avg_return'] and (x['win_rate'] > fixed['win_rate']
            or x['avg_return'] > fixed['avg_return'])]
    tiers = {
        'mean_win': base,
        'plus_final_worst_return': [x for x in base if x['worst_return'] >= fixed['worst_return']],
        'plus_worst_path_drawdown': [x for x in base if x['worst_path_drawdown'] >= target_path['worst_path_drawdown']],
        'plus_drawdown_daily_volatility': [x for x in base if x['worst_path_drawdown'] >= target_path['worst_path_drawdown']
                                          and x['mean_daily_volatility'] <= target_path['mean_daily_volatility']],
        'all_audited_risk_metrics': [x for x in base if x['worst_return'] >= fixed['worst_return']
            and x['std'] <= fixed['std'] and x['worst_path_drawdown'] >= target_path['worst_path_drawdown']
            and x['mean_path_drawdown'] >= target_path['mean_path_drawdown']
            and x['worst_intrahold_from_entry'] >= target_path['worst_intrahold_from_entry']
            and x['mean_daily_volatility'] <= target_path['mean_daily_volatility']]}
    return {name: {'count': len(rows), 'example': rows[0] if rows else None} for name, rows in tiers.items()}


def run(args):
    diagnosis = json.loads(Path(args.diagnosis).read_text())
    metrics = json.loads(Path(args.candidates).read_text())
    pools = defaultdict(list)
    for row in metrics['candidates']:
        pools[row['group'], row['ticker'], row['month']].append(row)
    # Small predefined family, motivated by new holding-path diagnostics.
    rules = [{'entry_step': step, 'risk_field': None, 'risk_cap': None, 'objective': name}
             for step in (7, 1) for name in ('win_mean', 'mean', 'win_median')]
    rules += [{'entry_step': step, 'risk_field': field, 'risk_cap': cap, 'objective': name}
              for step in (7, 1) for field in ('worst_path_drawdown', 'worst_intrahold_from_entry')
              for cap in (.05, .10, .15, .20, .30) for name in ('win_mean', 'mean', 'win_median')]

    def evaluate(rule, group):
        return [{'ticker': target['ticker'], **comparison({'month': target['month'], **target['expected']}, select(
            pools[group, target['ticker'], target['month']], rule))}
            for target in diagnosis['details'] if target['group'] == group]

    trials = [{'rule': rule, 'training': counts(evaluate(rule, 'training'))} for rule in rules]
    winner = max(trials, key=lambda r: training_key(r['training']))
    holdouts = {group: {'counts': counts(evaluate(winner['rule'], group)),
                       'details': evaluate(winner['rule'], group)} for group in ('GLD_10', 'SPY_QQQ_5')}
    dominance = []
    for target in diagnosis['details']:
        tiers = dominant_rows(pools[target['group'], target['ticker'], target['month']],
                              target, target['fixed_holding_path'])
        dominance.append({'group': target['group'], 'ticker': target['ticker'], 'month': target['month'],
                          'category': target['category'], 'tiers': tiers})
    tier_names = list(dominance[0]['tiers'])
    result = {'iterations': len(trials), 'trials': trials, 'winner': winner,
              'training_details': evaluate(winner['rule'], 'training'), 'holdouts': holdouts,
              'dominance_cases': {name: sum(r['tiers'][name]['count'] > 0 for r in dominance) for name in tier_names},
              'dominance_groups': {group: {name: sum(r['tiers'][name]['count'] > 0 for r in dominance if r['group'] == group)
                                          for name in tier_names} for group in ('training', 'GLD_10', 'SPY_QQQ_5')},
              'dominance_details': dominance,
              'minimum_uniform_path_cap_to_retain_all_training_references':
                  max(-r['fixed_holding_path']['worst_path_drawdown'] for r in diagnosis['details'] if r['group'] == 'training'),
              'hypothesis_status': 'Holding-path constraints are unconfirmed; unchanged source/tolerances; reused diagnostics.',
              'price_inputs': metrics['price_inputs'], 'input_audits': metrics['input_audits'],
              'production_changed': False, 'replication_complete': False}
    write_json(args.out, result)
    print('risk hypotheses', len(trials), 'winner', winner)
    print('held', {group: item['counts'] for group, item in holdouts.items()})
    print('dominance', result['dominance_cases'])
    print('minimum cap to retain training references', result['minimum_uniform_path_cap_to_retain_all_training_references'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnosis', default='results/diagnostics/selection_diagnosis.json')
    parser.add_argument('--candidates', default='results/diagnostics/selection_candidate_metrics.json')
    parser.add_argument('--out', default='results/research/holding_risk.json')
    run(parser.parse_args())
