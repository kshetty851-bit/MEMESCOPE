"""Synthetic wire-format tests; fixtures never enter the live book."""
import base64
import hashlib
import struct
from datetime import datetime, timezone
import pytest
from memescope_pretrade_ai.evidence import PROGRAM, Evidence, b58, history_features, observation
from memescope_pretrade_ai.service import map_row
from memescope_pretrade_ai.paper import PaperBook
AT=datetime.now(timezone.utc)
MINT,POOL=b58(b'm'*32),b58(b'p'*32)
def payload(name,size):
 d=bytearray(size); d[:8]=hashlib.sha256(('event:'+name).encode()).digest()[:8]
 struct.pack_into('<q',d,8,int(AT.timestamp())); return d
def tx(d):
 return {'meta':{'err':None,'logMessages':[f'Program {PROGRAM} invoke [1]','Program data: '+base64.b64encode(d).decode(),f'Program {PROGRAM} success']}}
def history():
 d=payload('CreatePoolEvent',205); d[50:82],d[173:205]=b'm'*32,b'p'*32
 result=[tx(d)]
 for side,quote in [('BuyEvent',200),('SellEvent',100)]:
  d=payload(side,184); d[120:152],d[152:184]=b'p'*32,b'u'*32
  struct.pack_into('<Q',d,64,quote); result.append(tx(d))
 return result
def test_history_requires_creation_and_counts_events():
 f=history_features(history(),POOL,MINT,AT)
 assert f['pool_lifetime_swaps'].value==2
 assert f['unique_buyers_30s'].value==1
 assert f['buy_sell_notional_ratio_30s'].value==2
 with pytest.raises(ValueError): history_features(history()[1:],POOL,MINT,AT)
 spoofed=history(); spoofed[0]['meta']['logMessages']=[s.replace(PROGRAM,'evil') for s in spoofed[0]['meta']['logMessages']]
 with pytest.raises(ValueError): history_features(spoofed,POOL,MINT,AT)
 truncated=history(); truncated[1]['meta']['logMessages'].append('Log truncated')
 with pytest.raises(ValueError): history_features(truncated,POOL,MINT,AT)
def test_no_sells_does_not_invent_ratio():
 assert 'buy_sell_notional_ratio_30s' not in history_features(history()[:2],POOL,MINT,AT)
def test_holder_coverage(monkeypatch):
 e=Evidence(); monkeypatch.setattr(e,'rpc',lambda *a:{'token_accounts':[{'address':'a','owner':'o','amount':90}]})
 with pytest.raises(ValueError): e.holders(MINT,100)
 assert e.holders(MINT,90)['top1_holder_share_pct'].value==100
def test_adapter_can_buy_only_with_complete_evidence(monkeypatch,tmp_path):
 e=Evidence()
 monkeypatch.setattr(e,'authorities',lambda mint:({k:observation(True,'test SPL') for k in ['mint_authority_safe','freeze_authority_safe']},6,100))
 monkeypatch.setattr(e,'holders',lambda *a:{k:observation(v,'test holders') for k,v in [('top1_holder_share_pct',5),('top10_holder_share_pct',20)]})
 monkeypatch.setattr(e,'history',lambda *a:history_features(history(),POOL,MINT,AT))
 def quote(mi,mo,amount):
  return {'outAmount':'10000000' if mo==MINT else '9900000','priceImpactPct':'0.001','routePlan':[{'swapInfo':{'ammKey':POOL}}]}
 monkeypatch.setattr(e,'quote',quote)
 row={'mint':MINT,'migrated_at':AT,'symbol':'TEST','ts':AT,'pair_address':POOL,'price_usd':1,'liquidity_usd':60000}
 snapshot=e.enrich(map_row(row,AT)); assert len(snapshot.opportunity.features)==14
 book=PaperBook(str(tmp_path/'test.db')); book.process(snapshot,datetime.now(timezone.utc))
 assert book.status(datetime.now(timezone.utc))['cash_usd']==90
 monkeypatch.setattr(e,'quote',lambda *a:{'outAmount':'10000000','routePlan':[{'swapInfo':{'ammKey':'other'}}]})
 missing=e.enrich(map_row(row,AT))
 assert missing.price is None
 assert 'sell_route_available' not in missing.opportunity.features

def test_token2022_extensions_fail_closed(monkeypatch):
 from memescope_pretrade_ai.evidence import TOKEN_2022
 e=Evidence()
 info={'isInitialized':True,'mintAuthority':None,'freezeAuthority':None,'decimals':6,'supply':'100','extensions':[{'extension':'tokenMetadata'}]}
 monkeypatch.setattr(e,'rpc',lambda *a:{'value':{'owner':TOKEN_2022,'data':{'parsed':{'info':info}}}})
 assert e.authorities(MINT)[0]['mint_authority_safe'].value is True
 info['extensions'].append({'extension':'transferHook'})
 with pytest.raises(ValueError,match='extension'): e.authorities(MINT)

def test_sell_uses_bid_not_buy_price(tmp_path):
 from conftest import make_op
 from memescope_pretrade_ai.paper import Snapshot
 from datetime import timedelta
 op=make_op(decision=AT).model_copy(update={'outcome':None})
 book=PaperBook(str(tmp_path/'bid.db')); book.process(Snapshot(op,1,AT),AT)
 later=AT+timedelta(minutes=5)
 exit_op=make_op(i=9,decision=later).model_copy(update={'outcome':None,'mint':op.mint,'pool':op.pool})
 book.process(Snapshot(exit_op,2,later,sell_price=.5),later)
 status=book.status(later)
 assert status['trades'][0]['side']=='SELL'
 assert status['trades'][0]['amount']<5
 assert status['cash_usd']<95

@pytest.mark.parametrize("buy_instruction", ["66063d1201daebea", "c62e1552b4d9e870", "c2ab1c46684d5b2f", "b817ee6167c5d33d", "694406af000723a2"])
def test_truncated_logs_recover_only_complete_cpi_coverage(buy_instruction):
 from memescope_pretrade_ai.evidence import events
 d=payload('BuyEvent',184)
 t={'transaction':{'message':{'accountKeys':[],'instructions':[{'programId':PROGRAM,'data':b58(bytes.fromhex(buy_instruction))}]}},'meta':{'err':None,'logMessages':['Log truncated'],'innerInstructions':[{'instructions':[{'programId':PROGRAM,'data':b58(bytes.fromhex('e445a52e51cb9a1d')+d)}]}]}}
 assert events(t)==[d]
 t['meta']['innerInstructions'][0]['instructions']=[]
 with pytest.raises(ValueError): events(t)

def test_provider_quota_is_reported_and_requests_back_off(monkeypatch):
 import io
 from urllib.error import HTTPError
 from memescope_pretrade_ai import evidence
 calls=[]
 def limited(*args,**kwargs):
  calls.append(1)
  raise HTTPError('https://provider.example',429,'limit',{},io.BytesIO(b'max usage reached'))
 monkeypatch.setattr(evidence,'urlopen',limited)
 client=Evidence()
 with pytest.raises(ValueError,match='quota exhausted'):client.read_json('Helius',None,1)
 with pytest.raises(ValueError,match='quota exhausted'):client.read_json('Helius',None,1)
 assert len(calls)==1
 assert 'Helius quota exhausted' in client.feed_error()
 client.cooldowns['Helius']=(0,'expired')
 assert client.feed_error() is None


def test_quotes_wait_for_chain_evidence_and_a_budget(monkeypatch):
 e=Evidence(); calls=[]
 monkeypatch.setattr(e,'authorities',lambda mint:(_ for _ in ()).throw(ValueError('Helius HTTP 401')))
 monkeypatch.setattr(e,'history',lambda *a:{})
 def quote(mi,mo,amount):
  e.spend_jupiter(); calls.append(mo)
  return {'outAmount':'10000000' if mo==MINT else '9900000','priceImpactPct':'0.001','routePlan':[{'swapInfo':{'ammKey':POOL}}]}
 monkeypatch.setattr(e,'quote',quote)
 row={'mint':MINT,'migrated_at':AT,'symbol':'TEST','ts':AT,'pair_address':POOL,'price_usd':1,'liquidity_usd':60000}
 skipped=e.enrich(map_row(row,AT))
 assert calls==[] and 'sell_route_available' not in skipped.opportunity.features
 held=e.enrich(map_row(row,AT),held=True)          # a held coin still gets its exit quote
 assert len(calls)==2 and 'sell_route_available' in held.opportunity.features
 from memescope_pretrade_ai import evidence as ev
 for _ in range(ev.JUPITER_PER_MINUTE): e.jupiter_calls.append(__import__('time').monotonic())
 with pytest.raises(ValueError): e.spend_jupiter()


def test_identity_from_creator_and_prior_pool_collapse():
 from datetime import timedelta
 from memescope_pretrade_ai.service import identity_of
 row={'creator':'C1','token_seen_at':AT-timedelta(minutes=3)}
 ident,f=identity_of(row,AT,{'C1':(2,AT-timedelta(days=3))})
 assert ident.creator_address=='C1' and f['identity_confidence'].value==1.0
 assert f['creator_prior_confirmed_rug_count_30d'].value==2 and round(f['malicious_link_recency_days'].value)==3
 ident,f=identity_of(row,AT,{})
 assert f['creator_prior_confirmed_rug_count_30d'].value==0 and 'malicious_link_recency_days' not in f
 assert identity_of({'creator':None,'token_seen_at':AT},AT,{})==(identity_of({},AT,{})[0],{})
 assert identity_of({'creator':'C1','token_seen_at':AT+timedelta(seconds=1)},AT,{})[1]=={}
