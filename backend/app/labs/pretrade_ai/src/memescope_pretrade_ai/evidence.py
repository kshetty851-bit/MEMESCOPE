"""Quote-only and public-chain evidence. No wallet, signing, or swap endpoints.

PumpSwap layout: pump-fun/pump-public-docs/idl/pump_amm.json.
History must include creation; truncated logs/history never prove a quiet pool.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
import struct
import time
from collections import deque
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import ObservedValue
from .paper import Snapshot

PROGRAM = 'pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA'
TOKEN_2022 = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
TOKEN = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
# The quote key is shared with the real wallets (2026-10-16): this lab asked for
# up to 40 quotes a cycle and was rate limited 812 times in 1,000 assessments,
# eating the allowance live buys and sells need. A per-minute budget, and quotes
# only for a held coin or a candidate whose chain evidence is already complete.
JUPITER_PER_MINUTE = int(os.environ.get('PRETRADE_JUPITER_PER_MINUTE', '6'))
# Chain reads go to the free public Solana node (Karthik, 2026-10-19), not
# Helius: its free credits are kept for the lab's open-buy check. That node
# also serves the graduation lab's quiet-pool count from the same server, so
# this lab spends at most RPC_PER_MINUTE calls and reuses a coin's chain facts
# for CHAIN_TTL_S instead of re-reading them on every pass.
RPC_PER_MINUTE = int(os.environ.get('PRETRADE_RPC_PER_MINUTE', '60'))
CHAIN_TTL_S = float(os.environ.get('PRETRADE_CHAIN_TTL_S', '20'))
AUTHORITY_TTL_S = 600
SIGNATURE_PAGE = 1000
RECENT_READS = 20      # trades read for the 30-second window; more and it stays unknown
NON_TRADE_INSTRUCTIONS = {'2d3da597680031bd': 'admin_cto_pool', 'd10b7357d5177ccc': 'admin_update_token_incentives', '694406af000723a2': 'boost_buy_and_burn', 'c2ab1c46684d5b2f': 'buy_exact_quote_in_v2', 'b817ee6167c5d33d': 'buy_v2', '253a237ebe35e4c5': 'claim_cashback', '1004471ccc01281b': 'claim_token_incentives', 'f945a4da9667548a': 'close_user_volume_accumulator', 'a039592ab58b2b42': 'collect_coin_creator_fee', 'c9cff3724b6f2fbd': 'create_config', 'f223c68952e1f2b6': 'deposit', 'b9adbb5ad80feee9': 'disable', 'ea66c2cb96483ee5': 'extend_account', '8ce9215e845ac28f': 'init_boost', '5e06ca73ff60e8b7': 'init_user_volume_accumulator', 'd0089f044aaf103a': 'migrate_pool_coin_creator', '2b644913e9f66f94': 'multi_hop_swap', '5df6823ce7e940b2': 'sell_v2', 'e3954c2a8227eacd': 'set_boost_authority', 'd295802dbc3a4eaf': 'set_coin_creator', '6faca2e87259d58e': 'set_reserved_fee_recipients', '20f6bf3408c949ba': 'sweep_creator_fee', '0830be07b644b7e5': 'sweep_protocol_fee', '561fc057a3574fee': 'sync_user_volume_accumulator', '75a1a04adf897663': 'toggle_boost', '7367e0ffbd5956c3': 'toggle_cashback_enabled', '01096fd0641fffa3': 'toggle_mayhem_mode', '8b348655e4e56cf1': 'transfer_creator_fees_to_pump', '01214eb921432c5c': 'transfer_creator_fees_to_pump_v2', 'a1b028d53cb8b3e4': 'update_admin', 'fbe0ab92a01a71e9': 'update_buyback_config', '3dafa0f9424288af': 'update_creator_fee_config', '68b867f258976b14': 'update_fee_config', 'b712469c946da122': 'withdraw'}
ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

def now():
    return datetime.now(timezone.utc)

def b58(raw):
    n, out = int.from_bytes(raw, 'big'), ''
    while n:
        n, r = divmod(n, 58)
        out = ALPHABET[r] + out
    return '1' * (len(raw)-len(raw.lstrip(b'\0'))) + out

def observation(value, source, at=None):
    return ObservedValue(value=value, observed_at=at or now(), source=source)

def b58decode(value):
    number = 0
    for char in value:
        number = number*58 + ALPHABET.index(char)
    return b'\0'*(len(value)-len(value.lstrip('1'))) + number.to_bytes((number.bit_length()+7)//8,'big')


def cpi_events(tx):
    """Recover truncated logs only when every trade/create instruction has its event.

    Anchor emit_cpi preserves events in complete inner instructions. Verify the
    program and instruction/event counts; never combine log and CPI duplicates.
    """
    from collections import Counter
    meta = tx['meta']
    if meta.get('innerInstructions') is None: raise ValueError('inner history unavailable')
    message = tx['transaction']['message']
    keys = [k['pubkey'] if isinstance(k,dict) else k for k in message['accountKeys']]
    instructions = list(message['instructions'])
    for group in meta['innerInstructions']: instructions.extend(group['instructions'])
    expected, actual, result = Counter(), Counter(), []
    mapping = {bytes.fromhex(k):hashlib.sha256(('event:'+v).encode()).digest()[:8] for k,v in {
        '66063d1201daebea':'BuyEvent','c62e1552b4d9e870':'BuyEvent',
        'c2ab1c46684d5b2f':'BuyEvent','b817ee6167c5d33d':'BuyEvent',
        '5df6823ce7e940b2':'SellEvent','694406af000723a2':'BuyEvent',
        '33e685a4017f83ad':'SellEvent','e992d18ecf6840bc':'CreatePoolEvent'}.items()}
    for instruction in instructions:
        program = instruction.get('programId')
        if program is None: program = keys[instruction['programIdIndex']]
        if program != PROGRAM: continue
        data = b58decode(instruction['data'])
        if data[:8] in mapping:
            expected[mapping[data[:8]]] += 1
        elif data[:8] == bytes.fromhex('e445a52e51cb9a1d'):
            if data[8:16] in mapping.values():
                actual[data[8:16]] += 1
                result.append(data[8:])
        elif data[:8].hex() not in NON_TRADE_INSTRUCTIONS:
            raise ValueError('unknown PumpSwap instruction')
    if expected != actual:
        raise ValueError('incomplete CPI event coverage')
    return result

def events(tx):
    """Only accept event logs while the verified PumpSwap program is executing."""
    meta = tx.get('meta') or {}
    if meta.get('err') is not None:
        return []
    if meta.get('innerInstructions') is not None and tx.get('transaction',{}).get('message'):
        return cpi_events(tx)
    logs = meta.get('logMessages')
    if logs is None or any('Log truncated' in s for s in logs):
        return cpi_events(tx)
    stack, result = [], []
    for line in logs:
        if line.startswith('Program ') and ' invoke [' in line:
            stack.append(line.split()[1])
        elif line.startswith('Program ') and (' success' in line or ' failed:' in line):
            if stack: stack.pop()
        elif line.startswith('Program data: ') and stack and stack[-1] == PROGRAM:
            result.append(base64.b64decode(line[14:], validate=True))
    return result

def pool_trades(transactions, pool, mint, at):
    """(created, trades) from verified PumpSwap events; a trade is
    (ts, is_buy, user, quote_amount)."""
    created, trades = False, []
    buy = hashlib.sha256(b'event:BuyEvent').digest()[:8]
    sell = hashlib.sha256(b'event:SellEvent').digest()[:8]
    creation = hashlib.sha256(b'event:CreatePoolEvent').digest()[:8]
    for tx in transactions:
        for data in events(tx):
            if data[:8] == creation and len(data) >= 205:
                if b58(data[173:205]) == pool and b58(data[50:82]) == mint:
                    created = True
            if data[:8] in (buy, sell):
                if len(data) < 184: raise ValueError('short trade event')
                if b58(data[120:152]) == pool:
                    ts = struct.unpack_from('<q', data, 8)[0]
                    if ts > at.timestamp(): raise ValueError('future trade')
                    trades.append((ts, data[:8] == buy, b58(data[152:184]), struct.unpack_from('<Q',data,64)[0]))
    return created, trades

def recent_features(trades, at, source):
    recent = [t for t in trades if 0 <= at.timestamp()-t[0] <= 30]
    result = {'unique_buyers_30s':len({t[2] for t in recent if t[1]})}
    bought = sum(t[3] for t in recent if t[1])
    sold = sum(t[3] for t in recent if not t[1])
    if sold: result['buy_sell_notional_ratio_30s'] = bought/sold
    return {k:observation(v, source, at) for k,v in result.items()}

def history_features(transactions, pool, mint, at):
    created, trades = pool_trades(transactions, pool, mint, at)
    if not created:
        if len(trades)>99:
            raise ValueError(f'quiet-pool limit exceeded: at least {len(trades)} verified swaps; older history not fetched')
        raise ValueError('pool creation absent from bounded history')
    result = {'pool_lifetime_swaps': observation(len(trades), 'confirmed PumpSwap events through pool creation', at)}
    result.update(recent_features(trades, at, 'confirmed PumpSwap events through pool creation'))
    return result

class Evidence:
    def __init__(self):
        self.rpc_url = os.environ.get('PRETRADE_RPC_URL')
        self.key = os.environ.get('PRETRADE_QUOTE_KEY')
        self.cooldowns = {}
        self.jupiter_calls = deque()
        self.rpc_calls = deque()
        self.chain_cache = {}
        self.authority_cache = {}
        self.tx_cache = {}

    def feed_error(self):
        active = [reason for until,reason in self.cooldowns.values() if until>time.monotonic()]
        return '; '.join(active) or None

    def read_json(self, provider, request, timeout):
        blocked = self.cooldowns.get(provider)
        if blocked and blocked[0]>time.monotonic():
            raise ValueError(blocked[1])
        try:
            with urlopen(request,timeout=timeout) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code == 429:
                body = error.read().decode(errors='replace').lower()
                quota = any(word in body for word in ['max usage','credits','monthly','quota','usage limit'])
                delay = 900 if quota else 120
                reason = f'{provider} quota exhausted; retry in 15 minutes' if quota else f'{provider} rate limited; retry in 2 minutes'
                self.cooldowns[provider] = (time.monotonic()+delay,reason)
                raise ValueError(reason) from None
            raise ValueError(f'{provider} HTTP {error.code}') from None

    def rpc_left(self):
        cutoff = time.monotonic() - 60
        while self.rpc_calls and self.rpc_calls[0] < cutoff:
            self.rpc_calls.popleft()
        return RPC_PER_MINUTE - len(self.rpc_calls)

    def rpc(self, method, params):
        if not self.rpc_url: raise ValueError('read-only RPC not configured')
        if self.rpc_left() <= 0: raise ValueError('RPC budget for this minute used; waiting')
        self.rpc_calls.append(time.monotonic())
        request = Request(self.rpc_url, data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(),headers={'Content-Type':'application/json'})
        value = self.read_json('RPC',request,8)
        if 'error' in value: raise ValueError('RPC rejected read')
        return value['result']

    def authorities(self, mint):
        hit = self.authority_cache.get(mint)
        if hit and time.monotonic() - hit[0] < AUTHORITY_TTL_S:
            return hit[1]
        value = self._authorities(mint)
        if len(self.authority_cache) > 2000: self.authority_cache.clear()
        self.authority_cache[mint] = (time.monotonic(), value)
        return value

    def _authorities(self, mint):
        account = self.rpc('getAccountInfo',[mint,{'encoding':'jsonParsed','commitment':'confirmed'}])['value']
        # Extensions require their own policy; do not mark Token-2022 safe by omission.
        if not account or account['owner'] not in (TOKEN,TOKEN_2022): raise ValueError('unsupported token program')
        info = account['data']['parsed']['info']
        if any(e.get('extension') not in {'metadataPointer','tokenMetadata'} for e in info.get('extensions',[])):
            raise ValueError('unreviewed token extension')
        if not info.get('isInitialized'): raise ValueError('uninitialized mint')
        return {'mint_authority_safe':observation(info['mintAuthority'] is None,'confirmed SPL mint account'),
                'freeze_authority_safe':observation(info['freezeAuthority'] is None,'confirmed SPL mint account')}, int(info['decimals']), int(info['supply'])

    def history(self, pool, mint):
        """The pool's lifetime transaction count from ONE signatures read.

        A page shorter than SIGNATURE_PAGE reaches the pool's first transaction,
        so the count is complete. It counts every succeeded transaction that
        touched the pool, set-up included, so it can only overstate the swaps:
        the cautious side for a quiet-pool rule. A full page proves nothing.
        """
        sigs = self.rpc('getSignaturesForAddress',[pool,{'limit':SIGNATURE_PAGE,'commitment':'confirmed'}])
        if not isinstance(sigs,list): raise ValueError('unexpected signatures format')
        if len(sigs) >= SIGNATURE_PAGE:
            raise ValueError(f'quiet-pool limit exceeded: at least {SIGNATURE_PAGE} transactions; older history not fetched')
        at = now()
        ok = [x for x in sigs if x.get('err') is None]
        result = {'pool_lifetime_swaps':observation(len(ok),'succeeded pool transactions through creation (public RPC signatures; an upper bound on swaps)',at)}
        window = [x for x in ok if (x.get('blockTime') or 0) >= at.timestamp()-30]
        if len(window) <= RECENT_READS:
            # A transaction never changes: each is read once, then remembered.
            txs = []
            for x in window:
                if x['signature'] not in self.tx_cache:
                    if len(self.tx_cache) > 5000: self.tx_cache.clear()
                    self.tx_cache[x['signature']] = self.rpc('getTransaction',[x['signature'],{'encoding':'jsonParsed','maxSupportedTransactionVersion':1,'commitment':'confirmed'}])
                if self.tx_cache[x['signature']]: txs.append(self.tx_cache[x['signature']])
            _, trades = pool_trades(txs, pool, mint, at)
            result.update(recent_features(trades, at, 'verified PumpSwap events of the last 30 seconds (public RPC)'))
        return result

    def jupiter_left(self):
        cutoff = time.monotonic() - 60
        while self.jupiter_calls and self.jupiter_calls[0] < cutoff:
            self.jupiter_calls.popleft()
        return JUPITER_PER_MINUTE - len(self.jupiter_calls)

    def spend_jupiter(self):
        if self.jupiter_left() <= 0:
            raise ValueError('Jupiter budget for this minute used; waiting')
        self.jupiter_calls.append(time.monotonic())

    def quote(self, mint_in, mint_out, amount):
        self.spend_jupiter()
        query = urlencode({'inputMint':mint_in,'outputMint':mint_out,'amount':str(amount),'slippageBps':50,'restrictIntermediateTokens':'true'})
        quote = self.read_json('Jupiter',Request('https://api.jup.ag/swap/v1/quote?'+query,headers={'x-api-key':self.key or ''}),4)
        if quote['inputMint'] != mint_in or quote['outputMint'] != mint_out or int(quote['inAmount']) != amount or int(quote['outAmount']) <= 0:
            raise ValueError('quote amount or mint mismatch')
        return quote

    def enrich(self, snapshot, held=False):
        op = snapshot.opportunity
        if self.feed_error():
            blocked = op.model_copy(update={'metadata':{**op.metadata,'evidence_errors':[self.feed_error()]}})
            return Snapshot(blocked,None,snapshot.quote_at,snapshot.symbol)
        features = dict(op.features)
        errors = []
        decimals = None
        cached = self.chain_cache.get(op.mint)
        if not held and not op.baseline_eligible:
            # Never buyable: no chain reads spent on it (the quotes below skip it too).
            cached = (time.monotonic(), {}, None, ['not baseline eligible: no chain reads'])
        if cached and time.monotonic() - cached[0] < CHAIN_TTL_S:
            _, chain, decimals, chain_errors = cached
        else:
            chain, chain_errors = {}, []
            with ThreadPoolExecutor(max_workers=2) as executor:
                history = executor.submit(self.history,op.pool,op.mint)
                try:
                    # No holder shares: the public node refuses getTokenLargestAccounts
                    # outright ("too many requests for a specific RPC call", 19 Oct)
                    # and they are not a required feature, so they stay unknown.
                    authority, decimals, _supply = self.authorities(op.mint)
                    chain.update(authority)
                except Exception as error: chain_errors.append('mint: '+(str(error) if isinstance(error,ValueError) else type(error).__name__))
                try: chain.update(history.result())
                except Exception as error: chain_errors.append('pool history: '+(str(error) if isinstance(error,ValueError) else type(error).__name__))
            if len(self.chain_cache) > 2000:
                self.chain_cache.clear()
            self.chain_cache[op.mint] = (time.monotonic(), chain, decimals, chain_errors)
        features.update(chain)
        errors.extend(chain_errors)
        price, sell_price, quoted_at = None, None, snapshot.quote_at
        # Last operation: both matched quotes must still be younger than five seconds.
        try:
            if not held and (errors or not op.baseline_eligible):
                raise ValueError('skipped until chain evidence is complete')
            if not held and self.jupiter_left() < 2:
                raise ValueError('Jupiter budget for this minute used; waiting')
            started = now()
            buy = self.quote(USDC,op.mint,10_000_000)
            sell = self.quote(op.mint,USDC,int(buy['outAmount']))
            if not all(any(step['swapInfo']['ammKey']==op.pool for step in q['routePlan']) for q in (buy,sell)):
                raise ValueError('quotes bypass candidate pool')
            at = now()
            features.update({
                'quote_age_seconds':observation((at-started).total_seconds(),'elapsed since matched quote request',at),
                'buy_price_impact_pct':observation(abs(float(buy['priceImpactPct']))*100,'Jupiter $10 ExactIn quote',at),
                'immediate_round_trip_loss_pct':observation(100*(1-int(sell['outAmount'])/10_000_000),'Jupiter matched output round trip, excluding network fees',at),
                'sell_route_available':observation(True,'Jupiter matched sell route',at)})
            if decimals is not None:
                price = 10/(int(buy['outAmount'])/10**decimals)
                sell_price = (int(sell['outAmount'])/1_000_000)/(int(buy['outAmount'])/10**decimals)
                quoted_at = started
        except Exception as error:
            features.pop('quote_age_seconds',None)
            errors.append('matched quotes: '+(str(error) if isinstance(error,ValueError) else type(error).__name__))
        at = now()
        if 'quote_age_seconds' in features:
            features['quote_age_seconds'] = observation((at-quoted_at).total_seconds(),'elapsed since matched quote request',at)
        if (at-snapshot.quote_at).total_seconds()>30:
            features.pop('liquidity_usd',None)
            errors.append('pool liquidity observation older than 30 seconds')
        updated = op.model_copy(update={'features':features,'decision_ts':at,'metadata':{**op.metadata,'evidence_errors':errors}})
        return Snapshot(updated,price,quoted_at,snapshot.symbol,sell_price)
