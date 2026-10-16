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

from .models import IdentitySnapshot as Identity, Opportunity, ObservedValue
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
 SELECT DISTINCT ON (mint) * FROM candidates ORDER BY mint, migrated_at DESC
)
SELECT c.mint,c.migrated_at,t.symbol,t.creator,t.first_seen_at AS token_seen_at,
 s.ts,s.pair_address,s.price_usd,s.liquidity_usd
FROM recent c LEFT JOIN grad_tokens t ON t.mint=c.mint
LEFT JOIN LATERAL (
 SELECT ts,pair_address,price_usd,liquidity_usd FROM grad_postgrad_samples
 WHERE mint=c.mint AND ts <= %(now)s AND ts >= %(now)s - interval '2 minutes'
 AND source IN ('dexscreener','held_ws')
 ORDER BY ts DESC LIMIT 1
) s ON true
ORDER BY (c.mint = ANY(%(held)s)) DESC, c.migrated_at DESC LIMIT 20
'''

# Creators whose earlier coin's pool collapsed (liquidity drained, recorded by
# the graduation lab's paper books) in the 30 days before now. A drained pool is
# an on-chain event, not a price loss alone (MAPPING_REQUIRED.md item 7).
RUGGED_CREATORS_SQL = '''
SELECT t.creator, count(DISTINCT p.mint) AS rugs, max(p.closed_at) AS last_rug
FROM grad_paper_positions p JOIN grad_tokens t ON t.mint = p.mint
WHERE p.close_reason = 'pool_collapsed' AND t.creator IS NOT NULL
  AND p.closed_at <= %(now)s AND p.closed_at > %(now)s - interval '30 days'
GROUP BY t.creator
'''


def identity_of(row, now: datetime, rugged: dict) -> tuple[Identity, dict]:
    """The coin's creator from pump.fun's create event (grad_tokens.creator) and
    its prior pool-collapse count. No creator on record stays unknown."""
    creator, seen = row.get('creator'), row.get('token_seen_at')
    if not creator or seen is None or seen > now:
        return Identity(), {}
    rugs, last = rugged.get(creator, (0, None))
    source = 'grad_tokens.creator (pump.fun create event)'
    features = {
        'identity_confidence': ObservedValue(value=1.0, observed_at=seen, source=source),
        'creator_prior_confirmed_rug_count_30d': ObservedValue(
            value=rugs, observed_at=now, quality='derived',
            source='grad_paper_positions pool_collapsed by this creator, 30 days'),
    }
    if last is not None:
        features['malicious_link_recency_days'] = ObservedValue(
            value=(now - last).total_seconds() / 86400, observed_at=now, quality='derived',
            source='grad_paper_positions latest pool_collapsed by this creator')
    return Identity(creator_address=creator, linkage_observed_at=seen, linkage_source=source), features


def map_row(row, now: datetime, rugged: dict | None = None) -> Snapshot:
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
    identity, known = identity_of(row, now, rugged or {})
    features.update(known)
    op = Opportunity(opportunity_id=f"forward:{row['mint']}:{now.isoformat()}", mint=row['mint'],
        pool=row['pair_address'] or 'unresolved', decision_ts=now,
        strategy_version='pretrade-paper-100-v1', universe='received pump migrations, last 15 minutes plus held mints',
        baseline_eligible=bool(row['pair_address'] and row['liquidity_usd'] and row['liquidity_usd'] >= 50000), features=features,
        identity=identity)
    return Snapshot(op, float(row['price_usd']) if row['price_usd'] is not None else None, at, row['symbol'])


def scan_once(book, connection, now, evidence=None):
    from psycopg.rows import dict_row
    with connection.transaction():
        connection.execute('SET TRANSACTION READ ONLY')
        connection.execute("SET LOCAL statement_timeout = '8s'")
        held = {p['mint'] for p in book.open_positions()}
        rows = connection.cursor(row_factory=dict_row).execute(SQL, {'now': now, 'held': list(held)}).fetchall()
        rugged = {r[0]: (r[1], r[2]) for r in connection.execute(RUGGED_CREATORS_SQL, {'now': now}).fetchall()}
    for row in rows:
        # Refresh the pool sample after preceding candidates' network reads.
        with connection.transaction():
            connection.execute('SET TRANSACTION READ ONLY')
            latest = connection.cursor(row_factory=dict_row).execute("SELECT ts,pair_address,price_usd,liquidity_usd FROM grad_postgrad_samples WHERE mint=%s AND ts<=now() AND ts>=now()-interval '2 minutes' AND source IN ('dexscreener','held_ws') ORDER BY ts DESC LIMIT 1", (row['mint'],)).fetchone()
        if latest:
            row.update(latest)
        decision_at = datetime.now(timezone.utc)
        snapshot = map_row(row, decision_at, rugged)
        if evidence is not None and row['pair_address']:
            snapshot = evidence.enrich(snapshot, held=row['mint'] in held)
        book.process(snapshot, datetime.now(timezone.utc))
        book.heartbeat(datetime.now(timezone.utc), evidence.feed_error() if evidence is not None else None, len(rows))
    book.heartbeat(datetime.now(timezone.utc), evidence.feed_error() if evidence is not None else None, len(rows))


def worker():
    import psycopg
    from .evidence import Evidence
    evidence = Evidence()
    book = PaperBook(STATE)
    while True:
        now = datetime.now(timezone.utc)
        try:
            with psycopg.connect(os.environ['PRETRADE_READ_DSN'], connect_timeout=5) as connection:
                scan_once(book, connection, now, evidence)
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
