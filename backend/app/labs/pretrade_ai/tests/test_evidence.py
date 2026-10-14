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
