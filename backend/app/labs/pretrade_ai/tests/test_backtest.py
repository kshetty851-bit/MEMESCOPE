from datetime import datetime, timedelta, timezone
from conftest import make_op
from memescope_pretrade_ai.backtest import run_selection_backtest
from memescope_pretrade_ai.config import AppConfig

def test_backtest_accounting():
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    rows=[make_op(i,start+timedelta(minutes=10*i),pnl=(1 if i%2 else -1),liquidity=56000) for i in range(6)]
    report=run_selection_backtest(rows,AppConfig())
    assert report["baseline"]["trades"]==6
    assert report["baseline"]["net_pnl_usd"]==0
    assert report["baseline"]["final_cash_usd"]==300
