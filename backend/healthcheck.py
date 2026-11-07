"""Container-local liveness check. No settings/dotenv imports or DB readiness RPCs."""
import json
import os
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def health_request(environ):
    hosts = json.loads(environ.get('ALLOWED_HOSTS', '[]'))
    if not isinstance(hosts, list):
        raise ValueError('ALLOWED_HOSTS must be a JSON list')
    host = environ.get('RAILWAY_PUBLIC_DOMAIN') or (hosts[0] if hosts else 'localhost')
    # The connection is always loopback; Host is only for API allowlist matching.
    return Request('http://127.0.0.1:8000/health', headers={'Host': host})


def main():
    try:
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(health_request(os.environ), timeout=4) as response:
            return 0 if response.status == 200 else 1
    except Exception:
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
