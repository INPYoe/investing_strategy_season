"""Offline stage-by-stage diagnosis, independent math, and holding-path audit.

Reference dates locate diagnostic rows; the selectors see only prices, month,
and one global profile. No website values are substituted into computed rows.
"""
import argparse
from collections import Counter
from dataclasses import asdict, replace
from datetime import date, timedelta
import csv
import hashlib
import html
import json
from pathlib import Path

from independent_window_math import calculate, objective, path_metrics, signature
from lab import FIELDS, comparison, dataset
from research_dividends import price_data
from research_selection_vintage import report_for_choice
from seasonality import Profile, all_windows, md, objective_key, selection_stats, write_json


LABELS = {'match': '전체 일치', 'reporting_or_input': '지정 구간 계산 차이',
          'candidate_generation': '후보에 기준 구간 없음', 'display_only': '같은 거래·표시 차이',
          'tie_order': '같은 점수·선택 순서 차이', 'ranking': '후보 존재·선택 점수 차이'}


def grid_rows(pool, profile):
    return [r for r in pool if (r['entry_day'] - profile.entry_offset) % profile.entry_step == 0]


def select_rows(pool, profile):
    available = [(r, selection_stats(r, profile.selection_history)) for r in pool]
    available = [(r, score) for r, score in available if score]
    return max(available, key=lambda pair: objective_key(pair[1], profile.objective))[0] if available else None


def classify(expected, fixed, chosen, grid, profile):
    if not comparison(expected, fixed)['all_match']:
        return 'reporting_or_input'
    if comparison(expected, chosen)['all_match']:
        return 'match'
    aliases = [r for r in grid if signature(r) == signature(fixed)]
    if not aliases:
        return 'candidate_generation'
    if signature(chosen) == signature(fixed):
        return 'display_only'
    if chosen and objective(fixed, profile.objective, profile.selection_history) == objective(
            chosen, profile.objective, profile.selection_history):
        return 'tie_order'
    return 'ranking'


def brief(row):
    if row is None:
        return None
    return {k: row[k] for k in (*FIELDS, 'median_return', 'worst_return', 'std')}


def independent_agreement(actual, oracle):
    if (actual is None) != (oracle is None):
        return {'matches': False, 'reason': 'observation availability differs'}
    if actual is None:
        return {'matches': True, 'maximum_numeric_difference': 0}
    exact = signature(actual) == signature(oracle) and all(actual[k] == oracle[k] for k in
            ('entry_day', 'exit_day', 'hold_days', 'sample_count'))
    errors = {k: abs(actual[k] - oracle[k]) for k in
              ('avg_return', 'win_rate', 'median_return', 'worst_return', 'std')}
    return {'matches': exact and max(errors.values()) <= 1e-12,
            'trade_dates_identical': signature(actual) == signature(oracle),
            'maximum_numeric_difference': max(errors.values()), 'numeric_differences': errors}


def years(row):
    return tuple(s['year'] for s in row['samples'])


def dominates(candidate, target):
    return (candidate['win_rate'] >= target['win_rate'] and candidate['avg_return'] >= target['avg_return']
            and (candidate['win_rate'] > target['win_rate'] or candidate['avg_return'] > target['avg_return']))


def rank_of_target(pool, fixed, profile):
    key = objective(fixed, profile.objective, profile.selection_history)
    eligible = [(row, objective(row, profile.objective, profile.selection_history)) for row in pool]
    eligible = [(row, score) for row, score in eligible if score is not None]
    better = sum(score > key for row, score in eligible)
    ties = sum(score == key for row, score in eligible)
    included = any(signature(row) == signature(fixed) for row, score in eligible)
    return {'in_pool_as_same_trades': included, 'better_scores': better,
            'tied_scores': ties, 'rank_range_if_available': [better + 1, better + ties] if included else None}


def diagnose(expected, pool, series, cutoff, period, profile, paths=None):
    fixed = next((r for r in pool if (r['entry_day'], r['hold_days']) ==
                  (expected['entry_day'], expected['hold_days'])), None)
    grid = grid_rows(pool, profile)
    chosen = select_rows(grid, profile)
    category = classify(expected, fixed, chosen, grid, profile)
    if fixed is None:
        return {'month': expected['month'], 'category': category, 'expected': expected,
                'actual': brief(chosen), 'fixed_window': None}
    same_years = [r for r in pool if years(r) == years(fixed)]
    dominators = sorted([r for r in same_years if dominates(r, fixed)],
                        key=lambda r: (r['win_rate'], r['avg_return']), reverse=True)
    aliases = [r for r in grid if signature(r) == signature(fixed)]
    def holding_path(row):
        return paths[row['entry_day'], row['hold_days']] if paths is not None else path_metrics(
            series.dates, series.prices, row)
    chosen_path = holding_path(chosen) if chosen else None
    fixed_path = holding_path(fixed)
    oracle_fixed = calculate(series.dates, series.prices, series.ticker, fixed['entry_day'], fixed['hold_days'],
                             cutoff, asdict(profile), period)
    return {'month': expected['month'], 'category': category, 'label': LABELS[category],
            'expected': {k: expected[k] for k in FIELDS}, 'actual': brief(chosen), 'fixed_window': brief(fixed),
            'fixed_comparison': comparison(expected, fixed), 'optimal_comparison': comparison(expected, chosen),
            'literal_reference_candidate_present': any((r['entry_day'], r['hold_days']) ==
                    (fixed['entry_day'], fixed['hold_days']) for r in grid),
            'same_trade_aliases_in_grid': [brief(r) for r in aliases],
            'selected_same_trades_as_reference': signature(chosen) == signature(fixed),
            'daily_candidates': len(pool), 'grid_candidates': len(grid),
            'reference_grid_rank': rank_of_target(grid, fixed, profile),
            'reference_daily_rank': rank_of_target(pool, fixed, profile),
            'reference_same_year_daily_rank': rank_of_target(same_years, fixed, profile),
            'same_year_dominator_count': len(dominators),
            'same_year_dominator_examples': [
                {**brief(r), 'avg_margin': r['avg_return'] - fixed['avg_return'],
                 'win_margin': r['win_rate'] - fixed['win_rate'],
                 'holding_path': holding_path(r)} for r in dominators[:3]],
            'fixed_trade_samples': fixed['samples'], 'selected_trade_samples': chosen['samples'] if chosen else [],
            'fixed_holding_path': fixed_path, 'selected_holding_path': chosen_path,
            'objective_values': {'reference': objective(fixed, profile.objective, profile.selection_history),
                                 'selected': objective(chosen, profile.objective, profile.selection_history) if chosen else None},
            'one_decimal_mean_and_win_tie': bool(chosen) and chosen['win_rate'] == fixed['win_rate']
                and f"{chosen['avg_return'] * 100:.1f}" == f"{fixed['avg_return'] * 100:.1f}",
            'independent_fixed_verification': independent_agreement(fixed, oracle_fixed)}


def input_audit(series, cutoff, period, calendar_sessions):
    first = max(series.dates[0], date(cutoff.year - period, 1, 1))
    last = min(series.dates[-1], cutoff - timedelta(days=1))
    observed = {d for d in series.dates if first <= d <= last}
    expected = {d for d in calendar_sessions if first <= d <= last}
    actual_digest = hashlib.sha256(json.dumps([(d.isoformat(), p) for d, p in zip(series.dates, series.prices)],
                                  separators=(',', ':')).encode()).hexdigest()
    return {'ticker': series.ticker, 'source': series.source, 'price_field': series.price_field,
            'base_source_sha256': series.sha256, 'evaluated_prices_sha256': actual_digest,
            'cutoff_exclusive': cutoff.isoformat(), 'period': period,
            'first_analyzed_session': first.isoformat(), 'last_analyzed_session': last.isoformat(),
            'missing_exchange_sessions': sorted(d.isoformat() for d in expected - observed),
            'unexpected_exchange_dates': sorted(d.isoformat() for d in observed - expected),
            'calendar_covers_analyzed_span': calendar_sessions[0] <= first and calendar_sessions[-1] >= last}


def html_report(path, result):
    body = []
    for row in result['details']:
        expected, actual = row['expected'], row['actual']
        def pair(field, percent=False, day=False):
            def fmt(value):
                return md(value) if day else f'{value * 100:.4f}%' if percent else str(value)
            return f"{fmt(expected[field])} / {fmt(actual[field]) if actual else '없음'}"
        rank = row.get('reference_grid_rank', {}).get('rank_range_if_available')
        cells = [row['group'], row['ticker'], str(row['month']), LABELS[row['category']],
                 pair('entry_day', day=True), pair('hold_days'), pair('avg_return', percent=True),
                 pair('win_rate', percent=True), pair('sample_count'), str(rank or '후보 없음'),
                 str(row.get('same_year_dominator_count', 0))]
        body.append('<tr>' + ''.join('<td>' + html.escape(x) + '</td>' for x in cells) + '</tr>')
    labels = ['자료', '종목', '월', '불일치 단계', '진입일 기준/계산', '보유일 기준/계산',
              '평균 기준/계산', '승률 기준/계산', '표본 기준/계산', '기준의 격자 내 순위', '동일 연도 우위 후보 수']
    markup = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>최적 구간 단계별 진단</title>
<style>body{font:15px system-ui;background:#f7f9fc;color:#17233b;margin:32px}main{max-width:1600px;margin:auto}table{border-collapse:collapse;background:white;width:100%}td,th{padding:10px;border-bottom:1px solid #dfe5ee;text-align:left;font-size:13px}code{white-space:pre-wrap}.scroll{overflow:auto}</style><main>
<h1>최적 구간 단계별 진단</h1><p>보관된 사이트 기준값과 하나의 연구 프로필을 비교합니다. 사이트 재현은 미완료입니다.</p>
<p>가격 복원·가격 갱신·윤년 가설이 포함되어 있습니다. 투자 모드의 실제 보유일 규칙을 변경하지 않습니다.
상위 캐시를 읽기 전용으로 재사용하며 새로운 외부 요청은 없습니다.</p>
<p>후보 포함 여부는 명목 날짜와 연도별 실제 진입·청산 벡터를 구분합니다. 우위 후보 수는 같은 진입 연도 집합의 평균·승률 비교이며 사이트의 숨은 제약을 증명하지 않습니다.</p>"""
    markup += '<p>분류: <code>' + html.escape(json.dumps(result['summary'], ensure_ascii=False)) + '</code></p>'
    markup += '<div class="scroll"><table><thead><tr>' + ''.join('<th>' + x + '</th>' for x in labels)
    markup += '</tr></thead><tbody>' + ''.join(body) + '</tbody></table></div></main></html>'
    Path(path).write_text(markup, encoding='utf-8')


def run(args):
    report_path = Path(args.profile)
    payload = json.loads(report_path.read_text())
    profile = Profile(**{**payload['profile'], 'holds': tuple(payload['profile']['holds'])})
    training, inputs = price_data(args, dataset(args.evidence, ['SPY', 'QQQ', 'AAPL']))
    frozen = {t: p for t, p, _, _ in training}
    with open(args.calendar) as stream:
        calendar_sessions = sorted(date.fromisoformat(r['Date']) for r in csv.DictReader(stream))
    groups = [('training', training, 10), ('GLD_10', dataset(args.evidence, ['GLD']), 10),
              ('SPY_QQQ_5', dataset(args.evidence, ['SPY', 'QQQ'], 5), 5)]
    details, pool_records, audits, disagreements, cache_checks, selection_checks = [], [], [], [], [], []
    maximum_numeric_error, candidate_count = 0, 0
    shared_report_cache = {}
    for group, data, period in groups:
        for ticker, original, refs, cutoff in data:
            series = frozen.get(ticker, original)
            audits.append({'group': group, **input_audit(series, cutoff, period, calendar_sessions)})
            indices = {d.isoformat(): i for i, d in enumerate(series.dates)}
            for ref in refs:
                pool = all_windows(series, ref['month'], cutoff, replace(profile, entry_step=1), period)
                oracle_pool = {}
                for day in range(1, 366):
                    if (date(2001, 1, 1) + timedelta(days=day - 1)).month != ref['month']:
                        continue
                    for hold in profile.holds:
                        oracle = calculate(series.dates, series.prices, ticker, day, hold,
                                           cutoff, asdict(profile), period)
                        if oracle is not None:
                            oracle_pool[day, hold] = oracle
                production_keys = {(r['entry_day'], r['hold_days']) for r in pool}
                if production_keys != set(oracle_pool):
                    disagreements.append({'group': group, 'ticker': ticker, 'month': ref['month'],
                        'candidate_availability_difference': {
                            'production_only': sorted(production_keys - set(oracle_pool)),
                            'independent_only': sorted(set(oracle_pool) - production_keys)}})
                oracle_grid = [r for (day, hold), r in oracle_pool.items()
                               if (day - profile.entry_offset) % profile.entry_step == 0]
                paths = {}
                for row in pool:
                    oracle = oracle_pool.get((row['entry_day'], row['hold_days']))
                    verification = independent_agreement(row, oracle)
                    maximum_numeric_error = max(maximum_numeric_error, verification.get('maximum_numeric_difference', 0))
                    candidate_count += 1
                    if not verification['matches']:
                        disagreements.append({'group': group, 'ticker': ticker, 'month': ref['month'],
                                              'entry_day': row['entry_day'], 'hold_days': row['hold_days'],
                                              'verification': verification})
                    path = path_metrics(series.dates, series.prices, row, indices)
                    paths[row['entry_day'], row['hold_days']] = path
                    pool_records.append({'group': group, 'ticker': ticker, 'month': ref['month'],
                                         **brief(row), 'sample_years': list(years(row)),
                                         **{key: value for key, value in path.items() if key not in ('details', 'basis')}})
                diagnostic = diagnose(ref, pool, series, cutoff, period, profile, paths)
                details.append({'group': group, 'ticker': ticker, 'period': period,
                                'cutoff_exclusive': cutoff.isoformat(), **diagnostic})
                chosen = select_rows(grid_rows(pool, profile), profile)
                valid = [(row, objective(row, profile.objective, profile.selection_history)) for row in oracle_grid]
                valid = [(row, score) for row, score in valid if score is not None]
                independently_selected = max(valid, key=lambda pair: pair[1])[0] if valid else None
                selection_checks.append({'group': group, 'ticker': ticker, 'month': ref['month'],
                    'same_selected_trades': signature(chosen) == signature(independently_selected),
                    'production': brief(chosen), 'independent': brief(independently_selected)})
                direct = report_for_choice(series, cutoff, period, chosen, {})
                warm = report_for_choice(series, cutoff, period, chosen, shared_report_cache)
                repeat = report_for_choice(series, cutoff, period, chosen, shared_report_cache)
                cache_checks.append({'group': group, 'ticker': ticker, 'month': ref['month'],
                                     'cold_warm_repeat_identical': direct == warm == repeat})
            print('diagnosed', group, ticker, flush=True)
    summary = {'cases': len(details), 'categories': dict(Counter(r['category'] for r in details)),
               'fixed_all_fields_match': sum(r.get('fixed_comparison', {}).get('all_match', False) for r in details),
               'same_year_dominated_cases': sum(r.get('same_year_dominator_count', 0) > 0 for r in details),
               'groups': {group: {'cases': sum(r['group'] == group for r in details),
                                 'categories': dict(Counter(r['category'] for r in details if r['group'] == group))}
                          for group, _, _ in groups}}
    result = {'profile': asdict(profile), 'profile_source': str(report_path), 'price_inputs': inputs,
              'input_audits': audits, 'summary': summary, 'details': details,
              'independent_math': {'candidate_windows_checked': candidate_count,
                  'disagreements': disagreements, 'maximum_numeric_difference': maximum_numeric_error,
                  'selection_checks': selection_checks, 'declared_conventions_only': True},
              'cache_checks': cache_checks,
              'scope': 'Existing diagnostic data, not fresh validation; source assumptions remain. Selectors do not take reference dates.',
              'new_network_requests': 0, 'production_optimizer_changed': False, 'replication_complete': False}
    out = Path(args.out)
    write_json(out / 'selection_diagnosis.json', result)
    write_json(out / 'selection_candidate_metrics.json', {'profile': asdict(profile), 'price_inputs': inputs,
               'input_audits': audits, 'candidates': pool_records, 'scope': result['scope']})
    html_report(out / 'selection_diagnosis.html', result)
    print('summary', summary)
    print('independent', candidate_count, 'mismatches', len(disagreements), 'numeric max', maximum_numeric_error)
    print('selected trade disagreement', sum(not r['same_selected_trades'] for r in selection_checks))
    print('cache disagreement', sum(not r['cold_warm_repeat_identical'] for r in cache_checks))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', default='evidence')
    parser.add_argument('--universe', default='config/universe.example.json')
    parser.add_argument('--actions', default='evidence/actions')
    parser.add_argument('--raw-cache', default='../market_detector/data/cache/prices')
    parser.add_argument('--raw-field', default='close')
    parser.add_argument('--append-raw-tail', action='store_true')
    parser.add_argument('--normalize-vintage', action='store_true')
    parser.add_argument('--profile', default='results/research/year_boundary/profile.json')
    parser.add_argument('--calendar', default='calendar.csv')
    parser.add_argument('--out', default='results/diagnostics')
    run(parser.parse_args())
