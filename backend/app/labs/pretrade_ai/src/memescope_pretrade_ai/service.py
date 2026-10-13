"""Read-only market discovery + paper-only service; not imported by platform workers."""
from __future__ import annotations

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import URLError

from .models import Opportunity, ObservedValue
from .paper import PaperBook, Snapshot

STATE = os.environ.get('PRETRADE_STATE', '/data/paper.sqlite3')
AUTH_URL = os.environ.get('PRETRADE_AUTH_URL', 'http://backend:8000/api/v1/alpha/session')

# Exact source semantics: m5 transaction counts are NOT lifetime swaps. Neither
# sample presence nor a positive price proves a working sell route.
SQL = '''
WITH candidates AS (
 SELECT mint, ts AS migrated_at FROM grad_migrations
 WHERE ts >= %(now)s - interval '15 minutes' AND ts <= %(now)s
 UNION
 SELECT mint, ts FROM grad_migrations WHERE mint = ANY(%(held)s)
), recent AS (
 SELECT * FROM candidates ORDER BY migrated_at DESC LIMIT 200
)
SELECT c.mint,c.migrated_at,t.symbol,s.ts,s.pair_address,s.price_usd,s.liquidity_usd
FROM recent c LEFT JOIN grad_tokens t ON t.mint=c.mint
LEFT JOIN LATERAL (
 SELECT ts,pair_address,price_usd,liquidity_usd FROM grad_postgrad_samples
 WHERE mint=c.mint AND ts <= %(now)s AND ts >= %(now)s - interval '2 minutes'
 AND source IN ('dexscreener','held_ws')
 ORDER BY ts DESC LIMIT 1
) s ON true
'''


def map_row(row, now: datetime) -> Snapshot:
    at = row['ts'] or now
    features = {}
    def feature(name, value, observed_at, source, quality='observed'):
        if value is not None:
            features[name] = ObservedValue(value=value, observed_at=observed_at, source=source, quality=quality)
    feature('liquidity_usd', float(row['liquidity_usd']) if row['liquidity_usd'] is not None else None, at, 'grad_postgrad_samples.liquidity_usd')
    if row['ts']:
        feature('quote_age_seconds', (now-at).total_seconds(), now, 'elapsed since grad_postgrad_samples.ts', 'derived')
    feature('graduation_age_seconds', (now-row['migrated_at']).total_seconds(), now, 'elapsed since grad_migrations.ts', 'derived')
    feature('signal_age_seconds', (now-row['migrated_at']).total_seconds(), now, 'elapsed since received migration', 'derived')
    op = Opportunity(opportunity_id=f"forward:{row['mint']}:{now.isoformat()}", mint=row['mint'],
        pool=row['pair_address'] or 'unresolved', decision_ts=now,
        strategy_version='pretrade-paper-100-v1', universe='received pump migrations, last 15 minutes plus held mints',
        baseline_eligible=bool(row['pair_address'] and row['liquidity_usd'] and row['liquidity_usd'] >= 50000), features=features)
    return Snapshot(op, float(row['price_usd']) if row['price_usd'] is not None else None, at, row['symbol'])


def scan_once(book, connection, now):
    from psycopg.rows import dict_row
    with connection.transaction():
        connection.execute('SET TRANSACTION READ ONLY')
        connection.execute("SET LOCAL statement_timeout = '8s'")
        rows = connection.cursor(row_factory=dict_row).execute(SQL, {'now': now, 'held': [p['mint'] for p in book.open_positions()]}).fetchall()
    for row in rows:
        decision_at = datetime.now(timezone.utc)
        book.process(map_row(row, decision_at), decision_at)
    book.heartbeat(datetime.now(timezone.utc), None, len(rows))


def worker():
    import psycopg
    book = PaperBook(STATE)
    while True:
        now = datetime.now(timezone.utc)
        try:
            with psycopg.connect(os.environ['PRETRADE_READ_DSN'], connect_timeout=5) as connection:
                scan_once(book, connection, now)
        except Exception as error:
            # Exception text may contain connection credentials: only expose class.
            book.heartbeat(now, f'Feed unavailable ({type(error).__name__}); entries paused.', 0)
        time.sleep(30)


def cors_headers(origin: str | None) -> dict[str, str]:
    # The lab must accept the website's credentialed GET when API_V1 uses the
    # API subdomain. Never wildcard or reflect an arbitrary requesting site.
    headers = {'Vary': 'Origin'}
    if origin in {'https://www.memescope.site', 'https://memescope.site'}:
        headers['Access-Control-Allow-Origin'] = origin
        headers['Access-Control-Allow-Credentials'] = 'true'
    return headers


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/api/v1/labs/pretrade-ai/status':
            self.reply(404, {'error': 'Not found'})
            return
        try:
            request = Request(AUTH_URL, headers={'Cookie': self.headers.get('Cookie', ''), 'Host': os.environ.get('PRETRADE_AUTH_HOST', 'api.memescope.site')})
            with urlopen(request, timeout=5) as response:
                session = json.load(response)
            if session.get('authenticated') is not True:
                self.reply(401, {'error': 'Alpha access required'})
                return
        except (URLError, ValueError, OSError):
            self.reply(503, {'error': 'Session validation unavailable'})
            return
        book = PaperBook(STATE)
        try:
            self.reply(200, book.status(datetime.now(timezone.utc)))
        finally:
            book.db.close()

    def reply(self, status, payload):
        body = json.dumps(payload, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        for name, value in cors_headers(self.headers.get('Origin')).items():
            self.send_header(name, value)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    os.makedirs(os.path.dirname(STATE) or '.', exist_ok=True)
    # OS lock prevents two scanner processes from sharing the same paper book.
    import fcntl
    lock = open(STATE + '.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    PaperBook(STATE).db.close()
    threading.Thread(target=worker, daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0', 8011), Handler).serve_forever()


if __name__ == '__main__':
    main()
