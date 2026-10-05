"""Read existing parent price files only. Never call acquisition adapters.

Optional pandas/pyarrow are used solely to read Parquet. Original files are
preserved, including conflicting or invalid final-session observations.
"""
import argparse
from collections import Counter
import csv
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path


def stored_date(value):
    return date.fromisoformat(str(value)[:10])


def inspect_rows(rows, columns, sessions, required_start, cutoff):
    columns = [str(c).lower().replace(' ', '_') for c in columns]
    prices = [c for c in ('open', 'high', 'low', 'close', 'adj_close') if c in columns]
    normalized = [{str(k).lower().replace(' ', '_'): v for k, v in row.items()} for row in rows]
    dates, failures, close_map = [], [], {}
    for number, row in enumerate(normalized, 1):
        try:
            current = stored_date(row['date'])
            dates.append(current)
        except (ValueError, TypeError, KeyError):
            failures.append({'row': number, 'kind': 'invalid_date'})
            continue
        numeric = {}
        for field in prices:
            try:
                value = float(row[field])
                if not math.isfinite(value) or value <= 0:
                    raise ValueError('nonpositive or nonfinite')
                numeric[field] = value
            except (ValueError, TypeError):
                failures.append({'row': number, 'date': current.isoformat(), 'kind': 'invalid_price', 'field': field})
        if 'close' in numeric:
            close_map[current.isoformat()] = numeric['close']
        if all(field in numeric for field in ('open', 'high', 'low', 'close')):
            if numeric['high'] < max(numeric['open'], numeric['low'], numeric['close']) or numeric['low'] > min(
                    numeric['open'], numeric['high'], numeric['close']):
                failures.append({'row': number, 'date': current.isoformat(), 'kind': 'invalid_ohlc',
                                 'values': {field: numeric[field] for field in ('open', 'high', 'low', 'close')}})
    counts = Counter(dates)
    unique = set(dates)
    first, last = min(dates) if dates else None, max(dates) if dates else None
    observed = {d for d in unique if d < cutoff}
    within = {d for d in sessions if first and first <= d <= last and d < cutoff}
    requested = {d for d in sessions if required_start <= d < cutoff}
    return {'records': len(rows), 'columns': columns, 'first_date': first.isoformat() if first else None,
            'last_date': last.isoformat() if last else None, 'has_adjusted_close_column': 'adj_close' in columns,
            'duplicate_dates': sorted(d.isoformat() for d, n in counts.items() if n > 1),
            'weekend_dates': sorted(d.isoformat() for d in unique if d.weekday() >= 5),
            'quality_failures': failures, 'within_file_missing_sessions': sorted(d.isoformat() for d in within - observed),
            'unexpected_exchange_dates': sorted(d.isoformat() for d in observed - set(sessions)),
            'requested_start': required_start.isoformat(), 'cutoff_exclusive': cutoff.isoformat(),
            'requested_missing_session_count': len(requested - observed),
            'covers_requested_sessions': bool(requested) and not requested - observed,
            'close_values': close_map, 'inferred_adjusted_close_values': False}


def read_file(path):
    if path.suffix == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            return list(reader), reader.fieldnames
    import pandas as pd
    frame = pd.read_parquet(path)
    return frame.to_dict('records'), list(frame.columns)


def date_range_record(path, records, first, last):
    decade = date(last.year - 10, last.month, min(last.day, 28) if last.month == 2 else last.day)
    return {'ticker': path.stem, 'records': records, 'first_date': first.isoformat(),
            'last_date': last.isoformat(), 'ten_calendar_year_span': first <= decade,
            'symbol_filename_is_numeric': path.stem.isdigit()}


def survey_summary(files, records, failures):
    return {'files': files, 'records': records, 'failures': failures,
            'first_year_counts': dict(Counter(r['first_date'][:4] for r in records)),
            'ten_calendar_year_span_count': sum(r['ten_calendar_year_span'] for r in records),
            'ten_year_non_numeric_filenames': [r for r in records if r['ten_calendar_year_span']
                                              and not r['symbol_filename_is_numeric']]}


def csv_date_survey(root):
    records, failures = [], []
    files = sorted(p for p in root.glob('*.csv') if not p.name.startswith('._'))
    for path in files:
        try:
            rows, columns = read_file(path)
            field = next(c for c in columns if c.lower() == 'date')
            dates = [stored_date(r[field]) for r in rows]
            records.append(date_range_record(path, len(rows), min(dates), max(dates)))
        except Exception as error:
            failures.append({'path': str(path), 'error_type': type(error).__name__, 'error': str(error)})
    return survey_summary(len(files), records, failures)


def metadata_survey(root):
    import pyarrow.parquet as pq
    records, failures = [], []
    files = sorted(p for p in root.glob('*.parquet') if not p.name.startswith('._'))
    for index, path in enumerate(files, 1):
        try:
            metadata = pq.ParquetFile(path).metadata
            dates = []
            for group in range(metadata.num_row_groups):
                block = metadata.row_group(group)
                for column in range(block.num_columns):
                    info = block.column(column)
                    if info.path_in_schema == 'date' and info.statistics and info.statistics.has_min_max:
                        dates.extend([stored_date(info.statistics.min), stored_date(info.statistics.max)])
            if not dates:
                dates = [stored_date(value) for value in pq.read_table(path, columns=['date']).column('date').to_pylist()]
            records.append(date_range_record(path, metadata.num_rows, min(dates), max(dates)))
        except Exception as error:
            failures.append({'path': str(path), 'error_type': type(error).__name__, 'error': str(error)})
        if index % 1000 == 0:
            print('surveyed parquet', index, '/', len(files), flush=True)
    return survey_summary(len(files), records, failures)


def run(args):
    parent = Path(args.parent).resolve()
    with open(args.calendar) as stream:
        sessions = [date.fromisoformat(row['Date']) for row in csv.DictReader(stream)]
    selected, maps = [], {}
    for ticker in args.tickers:
        for kind, root, extension in [('daily_parquet', parent / 'data/cache/prices/daily', '.parquet'),
                                      ('market_csv', parent / 'market_detector/data/cache/prices', '.csv')]:
            path = root / (ticker + extension)
            if not path.exists():
                selected.append({'ticker': ticker, 'cache': kind, 'path': str(path), 'exists': False})
                continue
            rows, columns = read_file(path)
            quality = inspect_rows(rows, columns, sessions, date.fromisoformat(args.start), date.fromisoformat(args.cutoff))
            maps[ticker, kind] = quality.pop('close_values')
            selected.append({'ticker': ticker, 'cache': kind, 'path': str(path), 'exists': True,
                'file_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'file_modified_at_utc': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                'provider_and_actual_collection_time': 'not verified per file', **quality})
    overlaps = []
    for ticker in args.tickers:
        first, second = maps.get((ticker, 'daily_parquet')), maps.get((ticker, 'market_csv'))
        if first is None or second is None:
            continue
        common = sorted(set(first) & set(second))
        different = [{'date': d, 'daily_parquet_close': first[d], 'market_csv_close': second[d],
                      'absolute_difference': abs(first[d] - second[d])} for d in common if first[d] != second[d]]
        overlaps.append({'ticker': ticker, 'overlapping_prices': len(common), 'exactly_different_prices': different})
    survey = metadata_survey(parent / 'data/cache/prices/daily') if args.survey_all else None
    csv_survey = csv_date_survey(parent / 'market_detector/data/cache/prices') if args.survey_all else None
    report = {'selected_file_quality': selected, 'close_comparisons': overlaps,
              'parquet_metadata_survey': {k: v for k, v in survey.items() if k != 'records'} if survey else None,
              'csv_date_survey': {k: v for k, v in csv_survey.items() if k != 'records'} if csv_survey else None,
              'network_requests': 0, 'parent_price_files_modified': False,
              'scope': 'Stored historical data audit only. No downloader, normalization fallback, or credential loading. '
                       'File modification time is not proven acquisition time. Ten-year span is not a proof of complete sessions.'}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'existing_price_quality.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    for ranges, filename in ((survey, 'parent_cache_date_ranges.csv'), (csv_survey, 'parent_csv_date_ranges.csv')):
        if not ranges:
            continue
        with (out / filename).open('w', newline='') as stream:
            fields = ['ticker', 'records', 'first_date', 'last_date', 'ten_calendar_year_span', 'symbol_filename_is_numeric']
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(ranges['records'])
        print('survey', filename, {k: v for k, v in ranges.items() if k not in ('records', 'ten_year_non_numeric_filenames')})
    print('quality', [(r['ticker'], r['cache'], len(r.get('quality_failures', [])),
                      r.get('covers_requested_sessions')) for r in selected if r['exists']])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', default='..')
    parser.add_argument('--tickers', nargs='+', default=['SPY', 'QQQ', 'GLD', 'AAPL', 'MSFT', 'NVDA', 'KO', 'JPM'])
    parser.add_argument('--calendar', default='calendar.csv')
    parser.add_argument('--start', default='2016-01-01')
    parser.add_argument('--cutoff', default='2026-10-01')
    parser.add_argument('--survey-all', action='store_true')
    parser.add_argument('--out', default='results/diagnostics')
    run(parser.parse_args())
