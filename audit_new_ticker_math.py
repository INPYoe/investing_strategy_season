"""Verify calculations on unused parent CSV tickers, without price acquisition.

These short histories verify the implementation on new inputs. They cannot
validate website selection parity: no website references exist for these cases.
Close and stored Adj Close are audited separately, never substituted.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import csv
from datetime import date
import hashlib
from pathlib import Path

from audit_existing_prices import inspect_rows
from independent_window_math import calculate, objective, signature
from research_selection_diagnosis import independent_agreement
from seasonality import PriceSeries, Profile, evaluate_window, objective_key, write_json


def run(args):
    cutoff = date.fromisoformat(args.cutoff)
    with open(args.calendar) as stream:
        sessions = [date.fromisoformat(row['Date']) for row in csv.DictReader(stream)]
    profile = Profile(cross_year_alignment='leap_after_first_year')
    groups, disagreements, inputs, selection_checks = [], [], [], []
    checked, max_error = 0, 0
    default_checked, default_available = 0, 0
    for ticker in args.tickers:
        path = Path(args.cache) / (ticker + '.csv')
        raw = path.read_bytes()
        rows = list(csv.DictReader(raw.decode('utf-8-sig').splitlines()))
        stored_fields = {name.lower().replace(' ', '_'): name for name in rows[0]}
        first = min(date.fromisoformat(r[stored_fields['date']][:10]) for r in rows)
        quality = inspect_rows(rows, list(rows[0]), sessions, first, cutoff)
        quality.pop('close_values')
        if (quality['quality_failures'] or quality['duplicate_dates'] or quality['within_file_missing_sessions']
                or quality['unexpected_exchange_dates'] or not quality['has_adjusted_close_column']):
            raise ValueError(f'{ticker}: inputs require quality review; no automatic repair')
        digest = hashlib.sha256(raw).hexdigest()
        inputs.append({'ticker': ticker, 'path': str(path.resolve()), 'sha256': digest, 'quality': quality,
                       'provider_and_actual_collection_time': 'unverified; past stored records only'})
        for field in ('Close', 'Adj Close'):
            stored_field = stored_fields[field.lower().replace(' ', '_')]
            series = PriceSeries.load(path, ticker, stored_field)
            # The real investment default must refuse an incomplete 10-year input.
            for day in range(1, 366):
                for hold in profile.holds:
                    actual = evaluate_window(series, day, hold, cutoff, profile, 10, 'investment')
                    oracle = calculate(series.dates, series.prices, ticker, day, hold,
                                       cutoff, asdict(profile), 10, 'investment')
                    default_checked += 1
                    default_available += actual is not None
                    if not independent_agreement(actual, oracle)['matches']:
                        disagreements.append({'ticker': ticker, 'field': field, 'period': 10,
                                              'mode': 'investment', 'day': day, 'hold': hold})
            for period in (2, 3):
                for mode in ('replica', 'investment'):
                    counts, production, independent = Counter(), defaultdict(list), defaultdict(list)
                    for day in range(1, 366):
                        for hold in profile.holds:
                            actual = evaluate_window(series, day, hold, cutoff, profile, period, mode)
                            oracle = calculate(series.dates, series.prices, ticker, day, hold,
                                               cutoff, asdict(profile), period, mode)
                            verification = independent_agreement(actual, oracle)
                            checked += 1
                            max_error = max(max_error, verification.get('maximum_numeric_difference', 0))
                            counts[actual['sample_count'] if actual else 'unavailable'] += 1
                            if not verification['matches']:
                                disagreements.append({'ticker': ticker, 'field': field, 'period': period,
                                                      'mode': mode, 'day': day, 'hold': hold,
                                                      'verification': verification})
                            if actual:
                                production[actual['month']].append(actual)
                            if oracle:
                                independent[oracle['month']].append(oracle)
                    for month in range(1, 13):
                        selected = max(production[month], key=lambda r: objective_key(r, profile.objective), default=None)
                        reference = max(independent[month], key=lambda r: objective(r, profile.objective), default=None)
                        selection_checks.append({'ticker': ticker, 'price_field': field, 'period': period,
                                                 'mode': mode, 'month': month,
                                                 'same_selected_trades': signature(selected) == signature(reference),
                                                 'same_window_labels': (selected is None and reference is None) or
                                                     bool(selected and reference and (selected['entry_day'], selected['hold_days']) ==
                                                          (reference['entry_day'], reference['hold_days']))})
                    groups.append({'ticker': ticker, 'price_field': field, 'period': period, 'mode': mode,
                                   'sample_count_distribution': dict(counts)})
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f'{ticker}: input changed during audit')
        print('checked existing CSV', ticker, flush=True)
    result = {'cutoff_exclusive': cutoff.isoformat(), 'profile': asdict(profile), 'inputs': inputs,
              'groups': groups, 'candidate_windows_checked': checked, 'maximum_numeric_difference': max_error,
              'disagreements': disagreements, 'selection_checks': selection_checks,
              'selection_disagreements': [r for r in selection_checks if not r['same_selected_trades'] or
                                         not r['same_window_labels']],
              'default_investment_10_year': {'windows_checked': default_checked,
                                             'available_windows': default_available},
              'network_requests': 0, 'price_files_modified': False,
              'new_site_reference_cases': 0, 'fresh_site_parity_validated': False,
              'scope': 'New ticker implementation verification on 2/3-year stored histories only. '
                       'This does not verify an unpublished website selection rule or full price provenance. '
                       'The default investment policy remains 10 completed observations.'}
    write_json(args.out, result)
    print('candidates', checked, 'disagreements', len(disagreements), 'max numeric difference', max_error)
    print('selection checks', len(selection_checks), 'disagreements', len(result['selection_disagreements']))
    print('default investment 10-year', result['default_investment_10_year'])
    if disagreements or result['selection_disagreements'] or default_available:
        raise SystemExit('Independent math/input validation failed; inspect artifact')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default='../market_detector/data/cache/prices')
    parser.add_argument('--tickers', nargs='+', default=['MSFT', 'NVDA', 'KO', 'JPM'])
    parser.add_argument('--calendar', default='calendar.csv')
    parser.add_argument('--cutoff', default='2026-05-21')
    parser.add_argument('--out', default='results/diagnostics/new_ticker_math.json')
    run(parser.parse_args())
