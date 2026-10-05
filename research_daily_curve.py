"""Reconstruct the public daily display from prices, without optimizer references.

This audit concerns the display only. Its success does not establish how optimal
entry dates or holding periods are selected. Rounding a date coordinate is an
observed label hypothesis, not a confirmed server implementation.
"""
import argparse
import hashlib
import json
import math
from functools import lru_cache
from datetime import date
from pathlib import Path
from statistics import mean

from seasonality import PriceSeries, write_json


def interpolate(values, index, size=252):
    if len(values) < 2 or size < 2 or not 0 <= index < size:
        raise ValueError('Interpolation needs at least two points and a valid index')
    position = index * (len(values) - 1) / (size - 1)
    lower, upper = math.floor(position), math.ceil(position)
    fraction = position - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction


def label_position(length, index, size=252, precision=None):
    position = index * (length - 1) / (size - 1)
    if precision is not None:
        position = round(position, precision)
    return min(length - 1, math.floor(position))


@lru_cache(maxsize=None)
def polynomial_weights(width, degree, offset):
    coordinates = list(range(offset, offset + width))
    matrix = [[sum(x ** (j + k) for x in coordinates) for k in range(degree + 1)]
              + [float(j == 0)] for j in range(degree + 1)]
    for column in range(degree + 1):
        pivot = max(range(column, degree + 1), key=lambda row: abs(matrix[row][column]))
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        divisor = matrix[column][column]
        matrix[column] = [value / divisor for value in matrix[column]]
        for row in range(degree + 1):
            if row == column:
                continue
            factor = matrix[row][column]
            matrix[row] = [value - factor * other for value, other in zip(matrix[row], matrix[column])]
    coefficients = [row[-1] for row in matrix]
    return tuple(sum(coefficient * x ** power for power, coefficient in enumerate(coefficients))
                 for x in coordinates)


def polynomial_smooth(values, width=11, degree=3):
    """Fit a local polynomial; fit boundary points on the nearest full window."""
    if width % 2 != 1 or not 0 <= degree < width <= len(values):
        raise ValueError('Invalid polynomial window')
    result = []
    for index in range(len(values)):
        first = min(max(0, index - width // 2), len(values) - width)
        weights = polynomial_weights(width, degree, first - index)
        result.append(sum(value * weight for value, weight in zip(values[first:first + width], weights)))
    return result


def daily_curves(series, cutoff, lookback=10, size=252):
    """Use only complete calendar years preceding cutoff's year."""
    if lookback < 1 or size < 2:
        raise ValueError('Invalid curve dimensions')
    yearly = {}
    for day, price in zip(series.dates, series.prices):
        if cutoff.year - lookback <= day.year < cutoff.year and day < cutoff:
            yearly.setdefault(day.year, []).append((day, price))
    curves = {}
    for year, rows in yearly.items():
        if len(rows) < 2:
            continue
        # An IPO/tail inside a year is not a full-year curve.
        if rows[0][0].month != 1 or rows[0][0].day > 7 or rows[-1][0].month != 12 or rows[-1][0].day < 24:
            continue
        dates, prices = zip(*rows)
        normalized = [p / prices[0] - 1 for p in prices]
        flags = [0.0] + [float(b > a) for a, b in zip(prices, prices[1:])]
        curves[year] = {
            'dates': dates,
            'returns': [interpolate(normalized, k, size) for k in range(size)],
            'daily_wins': [interpolate(flags, k, size) for k in range(size)],
        }
    return curves


def daily_display(curves, size=252, label_precision=None):
    if not curves:
        return []
    last_dates = curves[max(curves)]['dates']
    result = []
    for index in range(size):
        values = [curve['returns'][index] * 100 for curve in curves.values()]
        flags = [curve['daily_wins'][index] * 100 for curve in curves.values()]
        result.append({
            'date': last_dates[label_position(len(last_dates), index, size, label_precision)].strftime('%m-%d'),
            'avg': mean(values), 'max': max(values), 'min': min(values),
            'win_rate': mean(flags), 'count': len(values),
        })
    return result


def audit(prices_path, display_path, out):
    prices = PriceSeries.load(prices_path)
    payload = json.loads(Path(display_path).read_text())
    expected = payload['data']
    curves = daily_curves(prices, date(payload['endYear'], 1, 1),
                          payload['endYear'] - payload['startYear'], len(expected))
    actual = daily_display(curves, len(expected))
    smoothing_trials = []
    for width in range(5, 32, 2):
        for degree in (2, 3, 4):
            values = polynomial_smooth([row['avg'] for row in actual], width, degree)
            smoothing_trials.append({'window': width, 'degree': degree,
                                     'display_matches': sum(round(value, 3) == ref['avg_smooth']
                                                            for value, ref in zip(values, expected)),
                                     'mean_abs_error_percentage_points': mean(abs(value - ref['avg_smooth'])
                                                                             for value, ref in zip(values, expected))})
    smoothed = polynomial_smooth([row['avg'] for row in actual])
    for row, value in zip(actual, smoothed):
        row['avg_smooth'] = value
    details = [{'index': index, 'expected': ref, 'actual': row}
               for index, (ref, row) in enumerate(zip(expected, actual))]
    metrics = {}
    for field, digits in [('avg', 3), ('avg_smooth', 3), ('max', 3), ('min', 3), ('win_rate', 1)]:
        errors = [abs(row[field] - ref[field]) for ref, row in zip(expected, actual)]
        metrics[field] = {
            'display_matches': sum(round(row[field], digits) == ref[field] for ref, row in zip(expected, actual)),
            'cases': len(expected), 'mean_abs_error_percentage_points': mean(errors),
            'max_abs_error_percentage_points': max(errors),
        }
    label_trials = []
    for precision in (None, 0, 1, 2, 3, 4):
        labels = daily_display(curves, len(expected), precision)
        label_trials.append({'coordinate_rounding_digits': precision,
                             'matches': sum(ref['date'] == row['date'] for ref, row in zip(expected, labels))})
    result = {
        'model': 'Complete calendar years; first-price normalization; linear interpolation to common annual points',
        'years': sorted(curves), 'point_count': len(expected), 'metrics': metrics,
        'date_label_hypotheses': label_trials,
        'smoothing_hypotheses': smoothing_trials,
        'count_matches': sum(ref['count'] == row['count'] for ref, row in zip(expected, actual)),
        'price_sha256': prices.sha256,
        'display_sha256': hashlib.sha256(Path(display_path).read_bytes()).hexdigest(),
        'price_source': prices.source,
        'scope': 'Display reconstruction hypotheses only; optimal selection and server source not established',
        'replication_complete': False, 'details': details,
    }
    write_json(out, result)
    print({key: value for key, value in result.items() if key not in ('details', 'smoothing_hypotheses')})
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prices', default='evidence/SPY_chart.json')
    parser.add_argument('--display', default='evidence/SPY_daily.json')
    parser.add_argument('--out', default='results/research/daily_curve_audit.json')
    args = parser.parse_args()
    audit(args.prices, args.display, args.out)
