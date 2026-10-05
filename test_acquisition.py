"""Transport tests use fake responses only; no Yahoo requests are made."""
import io
import json
import socket
import tempfile
import unittest
import urllib.error
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from acquisition import failure_info, retry_after_info, yahoo_chart_url
from lab import download
from network_probe import NoRedirect, probe
from seasonality import PriceSeries


def limited(retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers['Retry-After'] = retry_after
    return urllib.error.HTTPError('https://query1.finance.yahoo.com/v8/finance/chart/SPY',
                                  429, 'Too Many Requests', headers, io.BytesIO(b'Too Many Requests'))


class AcquisitionTests(unittest.TestCase):
    def test_retry_after_delta_and_http_date_define_same_deadline(self):
        now = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
        delta = retry_after_info('120', now)
        absolute = retry_after_info('Mon, 05 Oct 2026 00:02:00 GMT', now)
        self.assertEqual(delta['not_before_utc'], absolute['not_before_utc'])
        self.assertEqual(delta['delay_seconds'], 120)
        self.assertFalse(retry_after_info('-1', now)['valid'])
        self.assertFalse(retry_after_info('later', now)['valid'])
        self.assertIsNone(retry_after_info(None, now)['not_before_utc'])

    def test_dns_failure_has_no_http_status_or_response_headers(self):
        detail = failure_info(urllib.error.URLError(socket.gaierror(8, 'name lookup failed')))
        self.assertEqual(detail['kind'], 'dns_error')
        self.assertIsNone(detail['http_status'])
        self.assertFalse(detail['http_response_received'])

    def test_probe_makes_one_attempt_on_429_and_records_header(self):
        opener = Mock()
        opener.open.side_effect = limited('1800')
        report = probe(yahoo_chart_url('SPY', '2026-09-28', '2026-10-03'), opener)
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(report['http_status'], 429)
        self.assertEqual(report['retry_after']['delay_seconds'], 1800)
        self.assertFalse(report['automatic_retry'])
        self.assertFalse(report['follow_redirects'])
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))

    def test_rate_limit_stops_batch_preserves_cache_and_blocks_until_retry_after(self):
        with tempfile.TemporaryDirectory(prefix='seasonality-rate-test-') as directory:
            path = Path(directory)
            cached = path / 'SPY.csv'
            cached.write_text('existing cache')
            args = Namespace(out=directory, provider='yahoo', tickers=['SPY', 'QQQ'],
                             start='2026-09-28', end='2026-10-03')
            with patch('lab.get_json', side_effect=limited('1800')) as request:
                self.assertEqual(download(args), 2)
                self.assertEqual(request.call_count, 1)
            self.assertEqual(cached.read_text(), 'existing cache')
            errors = json.loads((path / 'download_errors.json').read_text())
            self.assertEqual(errors[0]['http_status'], 429)
            self.assertEqual(errors[0]['retry_after']['raw'], '1800')
            with patch('lab.get_json') as request:
                self.assertEqual(download(args), 2)
                request.assert_not_called()

    def test_sdk_http_error_response_is_rate_limited_without_message_guessing(self):
        error = RuntimeError('provider error')
        error.response = Namespace(status_code=429, headers={'Retry-After': '60'})
        detail = failure_info(error)
        self.assertEqual(detail['kind'], 'http_429')
        self.assertEqual(detail['retry_after']['delay_seconds'], 60)

    def test_successful_download_keeps_close_adjusted_close_and_provenance(self):
        payload = {'chart': {'error': None, 'result': [{
            'meta': {'exchangeTimezoneName': 'America/New_York'},
            'timestamp': [1790602200, 1790688600],
            'indicators': {'quote': [{'close': [100, 101]}],
                           'adjclose': [{'adjclose': [99, 100]}]}}]}}
        with tempfile.TemporaryDirectory(prefix='seasonality-download-test-') as directory:
            args = Namespace(out=directory, provider='yahoo', tickers=['UNSEEN'],
                             start='2026-09-28', end='2026-10-03')
            with patch('lab.get_json', return_value=payload) as request:
                self.assertEqual(download(args), 0)
                self.assertEqual(request.call_count, 1)
            path = Path(directory) / 'UNSEEN.csv'
            close = PriceSeries.load(path, 'UNSEEN', 'Close')
            adjusted = PriceSeries.load(path, 'UNSEEN', 'Adj Close')
            self.assertEqual([d.isoformat() for d in close.dates], ['2026-09-28', '2026-09-29'])
            self.assertEqual(close.prices, [100, 101])
            self.assertEqual(adjusted.prices, [99, 100])
            metadata = json.loads(path.with_suffix('.metadata.json').read_text())
            self.assertEqual(metadata['sha256'], adjusted.sha256)
            self.assertEqual(metadata['end_exclusive'], args.end)
            self.assertEqual(metadata['records'], 2)

    def test_chart_bounds_use_exchange_midnight_and_exclusive_end(self):
        url = yahoo_chart_url('SPY', '2026-09-28', '2026-10-03')
        self.assertEqual(url, 'https://query1.finance.yahoo.com/v8/finance/chart/SPY?'
                         'period1=1790568000&period2=1791000000&interval=1d&events=div%2Csplits')
        with self.assertRaises(ValueError):
            yahoo_chart_url('SPY', '2026-10-03', '2026-09-28')


if __name__ == '__main__':
    unittest.main()
