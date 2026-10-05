"""Shared Yahoo request construction and transport diagnostics (no retries)."""
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo


def yahoo_chart_url(ticker, start, end):
    ny = ZoneInfo('America/New_York')
    first = int(datetime.combine(date.fromisoformat(start), datetime.min.time(), ny).timestamp())
    last = int(datetime.combine(date.fromisoformat(end), datetime.min.time(), ny).timestamp())
    if first >= last:
        raise ValueError('Price start must precede exclusive end')
    path = 'https://query1.finance.yahoo.com/v8/finance/chart/' + urllib.parse.quote(ticker, safe='')
    return path + '?' + urllib.parse.urlencode({
        'period1': first, 'period2': last, 'interval': '1d', 'events': 'div,splits'})


def json_request(url, body=None):
    return urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                  headers={'User-Agent': 'SeasonalityLab/0.1', 'Content-Type': 'application/json'})


def retry_after_info(value, received_at=None):
    now = received_at or datetime.now(timezone.utc)
    result = {'raw': value, 'valid': False, 'not_before_utc': None, 'delay_seconds': None}
    if value is None:
        return result
    value = value.strip()
    try:
        if re.fullmatch(r'[0-9]+', value):
            delay = int(value)
            until = now + timedelta(seconds=delay)
        else:
            until = parsedate_to_datetime(value)
            if until.tzinfo is None:
                return result
            until = until.astimezone(timezone.utc)
            delay = max(0, (until - now).total_seconds())
        result.update(valid=True, not_before_utc=until.isoformat(), delay_seconds=delay)
    except (ValueError, TypeError, OverflowError):
        pass
    return result


def failure_info(error, received_at=None):
    response = getattr(error, 'response', None)
    status = error.code if isinstance(error, urllib.error.HTTPError) else getattr(response, 'status_code', None)
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if status == 429:
        kind = 'http_429'
    elif status is not None:
        kind = 'http_error'
    elif isinstance(reason, socket.gaierror):
        kind = 'dns_error'
    elif isinstance(reason, PermissionError):
        kind = 'permission_error'
    elif isinstance(reason, TimeoutError):
        kind = 'timeout'
    elif 'RateLimit' in type(error).__name__:
        kind = 'sdk_rate_limit'
    elif re.search(r'\b429\b', str(error)):
        kind = 'suspected_rate_limit'
    else:
        kind = 'transport_error'
    headers = getattr(error, 'headers', None)
    if headers is None and response is not None:
        headers = getattr(response, 'headers', None)
    retry = headers.get('Retry-After') if headers is not None else None
    return {'kind': kind, 'error_type': type(error).__name__, 'error': str(error),
            'reason_type': type(reason).__name__, 'errno': getattr(reason, 'errno', None),
            'http_status': status, 'http_response_received': status is not None,
            'retry_after': retry_after_info(retry, received_at), 'automatic_retry': False}
