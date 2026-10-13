"""Isolated, persistent paper book. No wallet, signing, or order-provider imports."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import sqlite3

from .config import AppConfig
from .models import Opportunity
from .scoring import score_opportunity

STARTING_USD = 100.0
TICKET_USD = 10.0
MAX_ORDER_USD = 20.0
MAX_EXPOSURE_USD = 20.0
MAX_POSITIONS = 2
HOLD_SECONDS = 300
# Explicit paper assumptions, NOT measured execution costs.
FEE_SLIPPAGE = 0.005
FIXED_FEE_USD = 0.02


@dataclass(frozen=True)
class Snapshot:
    opportunity: Opportunity
    price: float | None
    quote_at: datetime
    symbol: str | None = None


def iso(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat()


def valid_quote(snapshot: Snapshot, now: datetime) -> bool:
    return bool(snapshot.price and math.isfinite(snapshot.price) and snapshot.price > 0
                and 0 <= (now - snapshot.quote_at).total_seconds() <= 5)


class PaperBook:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS account(id INTEGER PRIMARY KEY CHECK(id=1), cash REAL NOT NULL, booked REAL NOT NULL, month TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS positions(mint TEXT PRIMARY KEY, pool TEXT NOT NULL, symbol TEXT, opened_at TEXT NOT NULL, entry_cost REAL NOT NULL, quantity REAL NOT NULL, remaining REAL NOT NULL, proceeds REAL NOT NULL DEFAULT 0, closed_at TEXT);
            CREATE TABLE IF NOT EXISTS analyses(id INTEGER PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, at TEXT NOT NULL, mint TEXT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL, score TEXT NOT NULL, opportunity TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY, at TEXT NOT NULL, mint TEXT NOT NULL, side TEXT NOT NULL, amount REAL NOT NULL, quantity REAL NOT NULL, cost REAL NOT NULL, analysis_id INTEGER NOT NULL REFERENCES analyses(id));
            CREATE TABLE IF NOT EXISTS bookings(month TEXT PRIMARY KEY, at TEXT NOT NULL, amount REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO account VALUES(1,?,0,?)", (STARTING_USD, datetime.now(timezone.utc).strftime('%Y-%m')))
        self.config = AppConfig()

    def open_positions(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM positions WHERE closed_at IS NULL')]

    def heartbeat(self, now: datetime, error: str | None, count: int):
        with self.db:
            # Bound disk use; retain every assessment that produced a fill.
            self.db.execute("DELETE FROM analyses WHERE id < (SELECT id FROM analyses ORDER BY id DESC LIMIT 1 OFFSET 9999) AND id NOT IN (SELECT analysis_id FROM trades)")
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES('heartbeat',?)", (json.dumps({'at': iso(now), 'error': error, 'candidates': count}),))

    def process(self, snapshot: Snapshot, now: datetime):
        op = snapshot.opportunity
        if op.decision_ts > now or (now - op.decision_ts).total_seconds() > 5:
            raise ValueError('decision must be current and not in the future')
        # Use the supplied scorer unchanged. Never load the synthetic demo model.
        score = score_opportunity(op, self.config).model_dump(mode='json')
        with self.db:
            # Serialize balances, analyses and fills in the same transaction.
            self.db.execute('BEGIN IMMEDIATE')
            key = op.opportunity_id
            if self.db.execute('SELECT 1 FROM analyses WHERE event_key=?', (key,)).fetchone():
                return
            position = self.db.execute('SELECT * FROM positions WHERE mint=?', (op.mint,)).fetchone()
            action, reason = 'SKIP', '; '.join(score['reasons'])
            fresh = valid_quote(snapshot, now)
            if position and position['closed_at'] is None:
                due = (now - datetime.fromisoformat(position['opened_at'])).total_seconds() >= HOLD_SECONDS
                action, reason = 'HOLD', 'Five-minute paper holding period has not elapsed.'
                if due:
                    action, reason = 'SELL', 'Five-minute paper exit; current supplied-code assessment recorded before execution.'
                    if not fresh or position['pool'] != op.pool:
                        action, reason = 'EXIT_PENDING', 'Exit due, but no fresh quote from the entry pool. No sale or profit invented.'
            elif position:
                reason = 'Already traded this mint; no repeated entry.'
            elif score['decision'] == 'ACCEPT' and op.baseline_eligible and fresh and not op.outcome:
                account = self.db.execute('SELECT * FROM account WHERE id=1').fetchone()
                exposure, slots = self.db.execute('SELECT coalesce(sum(entry_cost),0),count(*) FROM positions WHERE closed_at IS NULL').fetchone()
                if account['cash'] >= TICKET_USD and slots < MAX_POSITIONS and exposure + TICKET_USD <= MAX_EXPOSURE_USD:
                    action, reason = 'BUY', 'ACCEPT under supplied scorer; $10 all-in paper entry within cash, order and exposure limits.'
                else:
                    reason = 'Cash, two-position limit or $20 total exposure limit prevents entry.'
            elif score['decision'] == 'ACCEPT':
                reason = 'Entry blocked: baseline eligibility, fresh quote or outcome-free forward input required.'
            cursor = self.db.execute('INSERT INTO analyses(event_key,at,mint,action,reason,score,opportunity) VALUES(?,?,?,?,?,?,?)',
                (key, iso(now), op.mint, action, reason, json.dumps(score), op.model_dump_json()))
            analysis_id = cursor.lastrowid
            if action == 'BUY':
                liquidity = float(op.features['liquidity_usd'].value)
                impact = TICKET_USD / (liquidity / 2)
                spendable = (TICKET_USD - FIXED_FEE_USD) / (1 + FEE_SLIPPAGE + impact)
                quantity = spendable / snapshot.price
                self.db.execute('UPDATE account SET cash=cash-? WHERE id=1', (TICKET_USD,))
                self.db.execute('INSERT INTO positions(mint,pool,symbol,opened_at,entry_cost,quantity,remaining) VALUES(?,?,?,?,?,?,?)',
                    (op.mint, op.pool, snapshot.symbol, iso(now), TICKET_USD, quantity, quantity))
                self.db.execute('INSERT INTO trades(at,mint,side,amount,quantity,cost,analysis_id) VALUES(?,?,?,?,?,?,?)',
                    (iso(now), op.mint, 'BUY', TICKET_USD, quantity, TICKET_USD-spendable, analysis_id))
            elif action == 'SELL':
                # At most $20 gross sale per fresh snapshot; larger winners exit in pieces.
                quantity = min(position['remaining'], MAX_ORDER_USD / snapshot.price)
                gross = min(MAX_ORDER_USD, quantity * snapshot.price)
                liquidity_obs = op.features.get('liquidity_usd')
                liquidity = float(liquidity_obs.value) if liquidity_obs and isinstance(liquidity_obs.value, (int, float)) else 0
                if liquidity <= 0:
                    self.db.execute("UPDATE analyses SET action='EXIT_PENDING',reason='Exit requires positive observed pool liquidity.' WHERE id=?", (analysis_id,))
                    return
                costs = min(gross, gross * (FEE_SLIPPAGE + gross / (liquidity / 2)) + FIXED_FEE_USD)
                proceeds = gross - costs
                remaining = max(0, position['remaining'] - quantity)
                self.db.execute('UPDATE account SET cash=cash+? WHERE id=1', (proceeds,))
                self.db.execute('UPDATE positions SET remaining=?,proceeds=proceeds+?,closed_at=? WHERE mint=?',
                    (remaining, proceeds, iso(now) if remaining <= position['quantity'] * 1e-12 else None, op.mint))
                self.db.execute('INSERT INTO trades(at,mint,side,amount,quantity,cost,analysis_id) VALUES(?,?,?,?,?,?,?)',
                    (iso(now), op.mint, 'SELL', gross, quantity, costs, analysis_id))
            self._book_month(now)

    def _book_month(self, now):
        month = now.strftime('%Y-%m')
        account = self.db.execute('SELECT * FROM account WHERE id=1').fetchone()
        if month > account['month'] and not self.db.execute('SELECT 1 FROM positions WHERE closed_at IS NULL').fetchone():
            profit = max(0, account['cash'] - STARTING_USD)
            self.db.execute('INSERT OR IGNORE INTO bookings VALUES(?,?,?)', (account['month'], iso(now), profit))
            self.db.execute('UPDATE account SET cash=cash-?,booked=booked+?,month=? WHERE id=1', (profit, profit, month))

    def status(self, now: datetime):
        account = dict(self.db.execute('SELECT * FROM account WHERE id=1').fetchone())
        heartbeat = self.db.execute("SELECT value FROM metadata WHERE key='heartbeat'").fetchone()
        heartbeat = json.loads(heartbeat[0]) if heartbeat else None
        running = bool(heartbeat and not heartbeat['error'] and 0 <= (now - datetime.fromisoformat(heartbeat['at'])).total_seconds() < 90)
        analyses = []
        for row in self.db.execute('SELECT id,at,mint,action,reason,score FROM analyses ORDER BY id DESC LIMIT 100'):
            item = dict(row)
            item['score'] = json.loads(item['score'])
            analyses.append(item)
        positions = [dict(r) for r in self.db.execute('SELECT * FROM positions ORDER BY opened_at DESC LIMIT 100')]
        realised = self.db.execute('SELECT coalesce(sum(proceeds-entry_cost),0) FROM positions WHERE closed_at IS NOT NULL').fetchone()[0]
        return {'mode': 'paper', 'running': running, 'heartbeat': heartbeat, 'starting_usd': STARTING_USD,
            'ticket_usd': TICKET_USD, 'max_order_usd': MAX_ORDER_USD, 'max_exposure_usd': MAX_EXPOSURE_USD,
            'hold_seconds': HOLD_SECONDS, 'cash_usd': account['cash'], 'booked_usd': account['booked'],
            'realised_usd': realised, 'model': 'rules-only-v1', 'trained_model': False,
            'analyses': analyses, 'analysis_count': self.db.execute('SELECT count(*) FROM analyses').fetchone()[0],
            'positions': positions, 'trades': [dict(r) for r in self.db.execute('SELECT * FROM trades ORDER BY id DESC LIMIT 100')],
            'cost_assumptions': '0.5% fee/slippage plus $0.02 per fill plus constant-product impact; simulation only.',
            'limitation': 'Live feed lacks verified lifetime swaps, executable sell routes, authority safety and identity/holder evidence. Incomplete candidates cannot buy. No real-data-trained model is available.'}
