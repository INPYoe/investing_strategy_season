"""Issue one GET to the exact default price API. Never retry or follow redirects."""
import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

from acquisition import failure_info, json_request, retry_after_info, yahoo_chart_url
from seasonality import write_json


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe(url, opener=None):
    opener = opener or urllib.request.build_opener(NoRedirect())
    request = json_request(url)
    report = {'captured_at_utc': datetime.now(timezone.utc).isoformat(), 'url': url,
              'method': request.get_method(), 'request_headers': dict(request.header_items()),
              'attempts': 1, 'follow_redirects': False, 'automatic_retry': False,
              'adapter': 'lab.download default yahoo; shared URL and request builders'}
    try:
        with opener.open(request, timeout=30) as response:
            report.update(kind='http_response', http_status=response.status,
                          http_response_received=True,
                          retry_after=retry_after_info(response.headers.get('Retry-After')),
                          response_headers={key: response.headers.get(key) for key in
                                            ('Retry-After', 'Date', 'Content-Type')})
            report['body_excerpt'] = response.read(300).decode('utf-8', errors='replace')
    except (urllib.error.URLError, OSError) as error:
        report.update(failure_info(error))
        if isinstance(error, urllib.error.HTTPError):
            report['response_headers'] = {key: error.headers.get(key) for key in
                                          ('Retry-After', 'Date', 'Content-Type')}
            report['body_excerpt'] = error.read(300).decode('utf-8', errors='replace')
            error.close()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker', default='SPY')
    parser.add_argument('--start', default='2026-09-28')
    parser.add_argument('--end', default='2026-10-03')
    parser.add_argument('--out', default='results/diagnostics/price_api_probe.json')
    args = parser.parse_args()
    result = probe(yahoo_chart_url(args.ticker, args.start, args.end))
    write_json(args.out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
