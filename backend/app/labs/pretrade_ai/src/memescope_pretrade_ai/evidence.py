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
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import ObservedValue
from .paper import Snapshot

PROGRAM = 'pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA'
TOKEN_2022 = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
TOKEN = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
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

def history_features(transactions, pool, mint, at):
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
    if not created:
        if len(trades)>99:
            raise ValueError(f'quiet-pool limit exceeded: at least {len(trades)} verified swaps; older history not fetched')
        raise ValueError('pool creation absent from bounded history')
    recent = [t for t in trades if 0 <= at.timestamp()-t[0] <= 30]
    result = {'pool_lifetime_swaps': len(trades), 'unique_buyers_30s':len({t[2] for t in recent if t[1]})}
    bought = sum(t[3] for t in recent if t[1])
    sold = sum(t[3] for t in recent if not t[1])
    if sold: result['buy_sell_notional_ratio_30s'] = bought/sold
    return {k:observation(v, 'confirmed PumpSwap events through pool creation',at) for k,v in result.items()}

class Evidence:
    def __init__(self):
        self.rpc_url = os.environ.get('PRETRADE_RPC_URL')
        self.key = os.environ.get('PRETRADE_QUOTE_KEY')

    def rpc(self, method, params):
        if not self.rpc_url: raise ValueError('read-only RPC not configured')
        request = Request(self.rpc_url, data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(),headers={'Content-Type':'application/json'})
        with urlopen(request, timeout=8) as response: value=json.load(response)
        if 'error' in value: raise ValueError('RPC rejected read')
        return value['result']

    def authorities(self, mint):
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
        options = {'transactionDetails':'full','encoding':'jsonParsed','maxSupportedTransactionVersion':1,'sortOrder':'desc','limit':100,'filters':{'status':'succeeded'},'commitment':'confirmed'}
        transactions = []
        for _ in range(3):
            result = self.rpc('getTransactionsForAddress',[pool,options])
            txs = result.get('data')
            if not isinstance(txs,list): raise ValueError('unexpected history format')
            transactions.extend(txs)
            try:
                return history_features(transactions,pool,mint,now())
            except ValueError as error:
                if str(error) != 'pool creation absent from bounded history': raise
            token = result.get('paginationToken')
            if not token: break
            options = {**options,'paginationToken':token}
        raise ValueError('pool creation absent from bounded history')

    def holders(self, mint, supply):
        owners, cursor, seen = {}, None, set()
        for _ in range(3):
            params = {'mint':mint,'limit':1000,'displayOptions':{'showZeroBalance':False}}
            if cursor: params['cursor'] = cursor
            result = self.rpc('getTokenAccounts',params)
            accounts = result['token_accounts']
            for account in accounts:
                if account['address'] in seen: raise ValueError('duplicate holder page')
                seen.add(account['address'])
                owner = account['owner']
                owners[owner] = owners.get(owner,0)+int(account['amount'])
            cursor = result.get('cursor')
            if not cursor or len(accounts)<1000: break
        else: raise ValueError('holder pagination incomplete')
        # Includes vault owners, conservatively. Refuse partial/stale indexed supply.
        total = sum(owners.values())
        if supply <= 0 or total != supply: raise ValueError('holder supply coverage incomplete')
        amounts = sorted(owners.values(),reverse=True)
        return {'top1_holder_share_pct':observation(100*amounts[0]/supply,'complete indexed owner balances, including vaults'),
                'top10_holder_share_pct':observation(100*sum(amounts[:10])/supply,'complete indexed owner balances, including vaults')}

    def quote(self, mint_in, mint_out, amount):
        query = urlencode({'inputMint':mint_in,'outputMint':mint_out,'amount':str(amount),'slippageBps':50,'restrictIntermediateTokens':'true'})
        with urlopen(Request('https://api.jup.ag/swap/v1/quote?'+query,headers={'x-api-key':self.key or ''}),timeout=4) as response:
            quote = json.load(response)
        if quote['inputMint'] != mint_in or quote['outputMint'] != mint_out or int(quote['inAmount']) != amount or int(quote['outAmount']) <= 0:
            raise ValueError('quote amount or mint mismatch')
        return quote

    def enrich(self, snapshot):
        op = snapshot.opportunity
        features = dict(op.features)
        errors = []
        decimals = None
        with ThreadPoolExecutor(max_workers=2) as executor:
            history = executor.submit(self.history,op.pool,op.mint)
            try:
                authority, decimals, supply = self.authorities(op.mint)
                features.update(authority)
                features.update(self.holders(op.mint,supply))
            except Exception as error: errors.append('mint/holders: '+(str(error) if isinstance(error,ValueError) else type(error).__name__))
            try: features.update(history.result())
            except Exception as error: errors.append('pool history: '+(str(error) if isinstance(error,ValueError) else type(error).__name__))
        price, sell_price, quoted_at = None, None, snapshot.quote_at
        # Last operation: both matched quotes must still be younger than five seconds.
        try:
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
