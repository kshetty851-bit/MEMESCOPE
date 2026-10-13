from datetime import datetime, timedelta, timezone
import pytest
from conftest import make_op
from memescope_pretrade_ai.paper import PaperBook, Snapshot
from memescope_pretrade_ai.service import map_row
NOW = datetime.now(timezone.utc).replace(microsecond=0)
def snap(i=0, now=NOW, price=1, mint=None):
    op = make_op(i=i, decision=now, mint=mint).model_copy(update={'outcome': None})
    return Snapshot(op, price, now)

def test_cash_cap_idempotency_restart_and_analysed_exit(tmp_path):
    path = str(tmp_path/'book.db')
    book = PaperBook(path)
    for s in [snap(), snap(), snap(1), snap(2)]: book.process(s, NOW)
    assert book.status(NOW)['cash_usd'] == 80
    assert len(book.status(NOW)['trades']) == 2
    book.db.close()
    book = PaperBook(path)
    later = NOW + timedelta(minutes=5)
    sell = snap(3, later, mint='m0')
    sell.opportunity.pool = 'p0'
    book.process(sell, later)
    state = book.status(later)
    assert 89 < state['cash_usd'] < 90
    assert len(state['trades']) == 3
    assert all(t['analysis_id'] for t in state['trades'])
    assert state['realised_usd'] < 0

def test_large_winner_sells_in_capped_pieces(tmp_path):
    book = PaperBook(str(tmp_path/'book.db'))
    book.process(snap(), NOW)
    for i in range(1,8):
        later = NOW+timedelta(minutes=5, seconds=i)
        sell = snap(i, later, price=10, mint='m0')
        sell.opportunity.pool = 'p0'
        book.process(sell, later)
    state = book.status(later)
    assert not book.open_positions()
    assert all(t['amount'] <= 20 for t in state['trades'])
    assert sum(t['quantity'] for t in state['trades'] if t['side']=='SELL') == pytest.approx(state['positions'][0]['quantity'])

def test_missing_stale_future_and_historical_inputs_cannot_buy(tmp_path):
    book = PaperBook(str(tmp_path/'book.db'))
    missing = snap()
    missing.opportunity.features.pop('sell_route_available')
    book.process(missing, NOW)
    stale = snap(1)
    book.process(Snapshot(stale.opportunity, 1, NOW-timedelta(seconds=6)), NOW)
    book.process(Snapshot(make_op(i=2, decision=NOW), 1, NOW), NOW)
    with pytest.raises(ValueError): book.process(snap(3, NOW+timedelta(seconds=1)), NOW)
    assert book.status(NOW)['cash_usd'] == 100
    assert not book.status(NOW)['trades']

def test_due_exit_waits_for_same_pool_fresh_quote(tmp_path):
    book = PaperBook(str(tmp_path/'book.db'))
    book.process(snap(), NOW)
    later = NOW+timedelta(minutes=5)
    book.process(snap(1, later, mint='m0'), later)
    assert book.status(later)['analyses'][0]['action'] == 'EXIT_PENDING'
    assert book.status(later)['cash_usd'] == 90

def test_live_mapping_does_not_fabricate_gate_evidence(tmp_path):
    snapshot = map_row({'mint':'real', 'migrated_at':NOW-timedelta(minutes=1), 'symbol':'REAL', 'ts':NOW, 'pair_address':'pool', 'price_usd':1, 'liquidity_usd':60000}, NOW)
    book = PaperBook(str(tmp_path/'book.db'))
    book.process(snapshot, NOW)
    state = book.status(NOW)
    assert state['analyses'][0]['score']['decision'] == 'INSUFFICIENT_DATA'
    assert state['cash_usd'] == 100
    assert 'pool_lifetime_swaps' not in snapshot.opportunity.features

def test_monthly_profit_booking_does_not_replenish_losses(tmp_path):
    book = PaperBook(str(tmp_path/'book.db'))
    with book.db:
        book.db.execute("UPDATE account SET cash=130,month='2020-01'")
        book._book_month(NOW)
    assert book.status(NOW)['cash_usd'] == 100
    assert book.status(NOW)['booked_usd'] == 30
    with book.db:
        book.db.execute("UPDATE account SET cash=70,month='2020-01'")
        book._book_month(NOW)
    assert book.status(NOW)['cash_usd'] == 70

def test_status_endpoint_checks_alpha_before_reading_book(monkeypatch, tmp_path):
    import io
    from memescope_pretrade_ai import service
    handler = service.Handler.__new__(service.Handler)
    handler.path = '/api/v1/labs/pretrade-ai/status'
    handler.headers = {'Cookie':'invalid'}
    replies = []
    handler.reply = lambda status, body: replies.append((status, body))
    monkeypatch.setattr(service, 'STATE', str(tmp_path/'book.db'))
    def denied(request, **kwargs):
        assert request.get_header('Host') == 'api.memescope.site'
        assert request.get_header('Cookie') == 'invalid'
        return io.BytesIO(b'{"authenticated":false}')
    monkeypatch.setattr(service, 'urlopen', denied)
    handler.do_GET()
    assert replies[-1][0] == 401
    assert not (tmp_path/'book.db').exists()
    monkeypatch.setattr(service, 'urlopen', lambda *args, **kwargs: io.BytesIO(b'{"authenticated":true}'))
    handler.do_GET()
    assert replies[-1][0] == 200
    assert replies[-1][1]['cash_usd'] == 100
    def unavailable(*args, **kwargs): raise OSError('unavailable')
    monkeypatch.setattr(service, 'urlopen', unavailable)
    handler.do_GET()
    assert replies[-1][0] == 503

def test_credentialed_cors_only_allows_the_existing_website():
    from memescope_pretrade_ai.service import cors_headers
    for origin in ('https://www.memescope.site', 'https://memescope.site'):
        assert cors_headers(origin)['Access-Control-Allow-Origin'] == origin
        assert cors_headers(origin)['Access-Control-Allow-Credentials'] == 'true'
    for origin in (None, 'null', 'https://www.memescope.site.evil.test', 'https://evil.test'):
        assert 'Access-Control-Allow-Origin' not in cors_headers(origin)
        assert 'Access-Control-Allow-Credentials' not in cors_headers(origin)
