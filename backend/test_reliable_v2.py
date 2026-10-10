import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from engine import BacktestEngine, CostModel
from factor_lab.causal import generate_predictions
from job_service import JobStore
from research_contracts import historical_universe, ExecutionDataService, DataContractError, persist_snapshot, TradingCalendar
from virtual_trading_v2 import dump_engine, restore_engine


def bars(n=8, code="600000"):
    rows = []
    for i, d in enumerate(pd.bdate_range("2024-01-01", periods=n)):
        raw = 10 + i*.1
        rows.append({"date": d.strftime("%Y-%m-%d"), "stock_code": code, "stock_name": code,
                     "open": raw*.5, "close": raw*.5, "high": raw*.5, "low": raw*.5,
                     "raw_open": raw, "raw_close": raw, "raw_high": raw, "raw_low": raw, "raw_prev_close": raw-.1,
                     "volume": 1000000, "amount": raw*1000000, "settlement_days": 1, "tradestatus": "1"})
    return pd.DataFrame(rows)


def test_universe_ignores_future_and_includes_quarantined_history(tmp_path):
    old = tmp_path / "_removed_st_delisted"
    old.mkdir()
    dates = pd.bdate_range("2023-11-01", "2024-03-01").strftime("%Y-%m-%d")
    for code, directory, amount in [("000001",tmp_path,10.),("000002",old,20.)]:
        pd.DataFrame({"date":dates, "amount":amount}).to_parquet(directory / f"{code}_full_history.parquet")
    manager = SimpleNamespace(cache_dir=tmp_path, is_etf_symbol=lambda c: False)
    before, meta = historical_universe(manager,1,"2023-12-31")
    path = tmp_path / "000001_full_history.parquet"
    f = pd.read_parquet(path)
    f.loc[f.date > "2023-12-31","amount"] = 1e10
    f.to_parquet(path)
    after, _ = historical_universe(manager,1,"2023-12-31")
    assert before == after == ["000002"]
    assert meta["survivorship_bias_free"] is False


def test_snapshot_hash_tracks_only_supplied_history(tmp_path):
    f = bars()
    one = persist_snapshot(f, {}, {}, tmp_path)
    assert persist_snapshot(f.sample(frac=1), {}, {}, tmp_path) == one
    f.loc[0,"raw_close"] += 1
    assert persist_snapshot(f, {}, {}, tmp_path) != one


def test_strict_execution_never_silently_uses_adjusted_prices(tmp_path, monkeypatch):
    service = ExecutionDataService(None,tmp_path)
    monkeypatch.setattr(service,"_load_raw",lambda *a: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(DataContractError, match="未复权"):
        service.prepare(bars().drop(columns=[c for c in bars() if c.startswith("raw_")]))


def test_unknown_company_action_blocks_strict_mode(tmp_path):
    f = bars()
    f.loc[4:,"close"] *= .9
    with pytest.raises(DataContractError, match="公司行动"):
        ExecutionDataService(None,tmp_path).prepare(f)


def test_signal_prices_and_execution_prices_are_separate():
    f=bars()
    observed=[]
    def signal(date, day):
        observed.append(float(day.iloc[0].close))
        return {"600000":.5}
    engine=BacktestEngine(stock_stop_loss=-.9)
    result=engine.run_backtest(f,signal,f.date.min(),f.date.max())
    assert observed[1] == f.iloc[1].close
    assert result["trades"][0]["price"] == f.iloc[1].raw_open


def test_live_ledger_roundtrip_matches_backtest_with_t1_and_costs():
    f=bars()
    weights={date:({"600000":.5} if i<4 else {}) for i,date in enumerate(f.date)}
    backtest=BacktestEngine(stock_stop_loss=-.9)
    backtest.run_backtest(f,lambda date,day:weights[date],f.date.min(),f.date.max())
    paper=BacktestEngine(stock_stop_loss=-.9)
    paper._reset_diagnostics()
    pending=None
    for date, day in f.groupby("date",sort=False):
        paper.step(date,day,pending)
        pending=weights[date]
        # Serialize/restart every day, as real paper accounts do.
        paper=restore_engine(dump_engine(paper,pending))
        paper.stock_stop_loss=-.9
    assert paper.trades == backtest.trades
    assert paper.portfolio.cash == backtest.portfolio.cash
    assert paper.portfolio.total_value == backtest.portfolio.total_value


@pytest.mark.parametrize("settlement,expected",[(0,0),(1,1)])
def test_t0_vs_t1_sell_availability(settlement,expected):
    f=bars(2,"518880")
    f["settlement_days"]=settlement
    f.loc[1,"raw_low"]=8.
    f.loc[1,"raw_close"]=8.
    engine=BacktestEngine()
    engine.run_backtest(f,lambda *a:{"518880":.5},f.date.min(),f.date.max())
    assert len(engine.portfolio.positions) == expected


def test_explicit_split_and_cash_dividend_receivable_are_accounted():
    f=bars(4)
    f["share_multiplier"]=1.
    f["cash_dividend_per_share"]=0.
    f["dividend_pay_date"]=""
    f.loc[2,"share_multiplier"]=2.
    f.loc[2,"cash_dividend_per_share"]=1.
    f.loc[2,"dividend_pay_date"]=f.loc[3,"date"]
    f.loc[2:, ["raw_open","raw_high","raw_low","raw_close","raw_prev_close"]] /= 2
    engine=BacktestEngine(stock_stop_loss=-.9)
    engine._reset_diagnostics()
    engine.step(f.loc[1,"date"],f.iloc[[1]],{"600000":.5})
    qty=engine.portfolio.positions["600000"].quantity
    cash=engine.portfolio.cash
    engine.step(f.loc[2,"date"],f.iloc[[2]],None)
    assert engine.portfolio.positions["600000"].quantity == qty*2
    assert engine.portfolio.cash == cash
    assert sum(r["amount"] for r in engine.portfolio.dividend_receivables)==qty
    engine.step(f.loc[3,"date"],f.iloc[[3]],None)
    assert engine.portfolio.cash == cash+qty
    entry_notional = engine._open_round_trips['600000']['entry_notional']
    assert engine._open_round_trips['600000']['qty'] == qty * 2
    engine._close_position(f.loc[3,'date'], '600000', float(f.loc[3,'raw_close']), 'sell')
    trip = engine.round_trips[-1]
    assert trip['dividend_amount'] == qty
    assert trip['gross_pnl'] == pytest.approx(trip['exit_notional'] + qty - entry_notional)


def test_jobs_persist_cancel_and_recover(tmp_path):
    store=JobStore(tmp_path/"jobs.db")
    queued=store.create("backtest",{})
    running=store.claim()
    assert queued==running
    restarted=JobStore(store.path)
    restarted.recover()
    assert restarted.get(queued)["status"]=="interrupted"
    new=store.create("backtest",{})
    store.update(new,status="canceled")
    store.update(new,status="succeeded",result={"invalid":True})
    assert store.get(new)["status"]=="canceled"


def test_all_600_trades_survive_persistence_and_pagination(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from research_api import make_router
    store=JobStore(tmp_path/"jobs.db")
    job=store.create("backtest",{})
    store.update(job,status="succeeded",result={"trades":[{"i":i} for i in range(600)]})
    app=FastAPI()
    app.include_router(make_router(store,None,None,None,lambda r:None))
    client=TestClient(app)
    assert client.get(f"/api/research/jobs/{job}/trades?offset=550&limit=100").json()=={"items":[{"i":i} for i in range(550,600)],"total":600,"offset":550,"limit":100}
    assert len(client.get(f"/api/research/jobs/{job}/trades.csv").text.splitlines())==601


def test_calendar_uses_exchange_dates_not_weekday_guesses(tmp_path):
    path=tmp_path/"calendar.json"
    path.write_text(json.dumps(["2024-02-08","2024-02-19"]))
    assert TradingCalendar(path).dates("2024-02-09","2024-02-19")==["2024-02-19"]
    with pytest.raises(DataContractError):
        TradingCalendar(path).dates("2024-02-09","2025-01-01")


def test_fold_recipe_and_predictions_ignore_future_changes():
    dates=pd.bdate_range("2023-01-01",periods=220).strftime("%Y-%m-%d")
    rng=np.random.default_rng(7)
    rows=[]
    features=[f"f{i}" for i in range(5)]
    for i,date in enumerate(dates):
        for code in range(5):
            rows.append({"date":date,"stock_code":str(code),"label_end_date":dates[min(i+5,len(dates)-1)],"label_reg":rng.normal(),"split":"test",**dict(zip(features,rng.normal(size=5)))})
    f=pd.DataFrame(rows)
    first=generate_predictions(f,features,7,rf_n_estimators=4)
    changed=f.copy()
    changed.loc[changed.date>dates[179],features+['label_reg']]=999.
    second=generate_predictions(changed,features,7,rf_n_estimators=4)
    mask=first['scored'].date<=dates[179]
    pd.testing.assert_series_equal(first['scored'].loc[mask,'walk_forward_composite_score'],second['scored'].loc[mask,'walk_forward_composite_score'])
    assert first['summary']['folds'][0]==second['summary']['folds'][0]
    assert first['summary']['folds'][0]['prediction_start']==dates[160]


def test_legacy_ml_manifest_cannot_be_marked_ready(tmp_path):
    from factor_lab.strategy import get_factor_lab_artifact_readiness
    (tmp_path/'latest_manifest.json').write_text(json.dumps({'run_id':'old','config_hash':'old'}))
    assert not get_factor_lab_artifact_readiness(tmp_path)['ready']


def test_queue_bounds_real_processes_and_cancels_running_work(tmp_path):
    import time
    from job_service import JobQueue
    worker = tmp_path / 'slow_worker.py'
    worker.write_text('import sys,time\nfrom job_service import JobStore\ns=JobStore(sys.argv[1])\ntime.sleep(.8)\ns.update(sys.argv[2],status="succeeded",result={"ok":True})\n')
    store = JobStore(tmp_path / 'jobs.db')
    queue = JobQueue(store, worker)
    try:
        ids = [queue.submit('backtest', {}) for _ in range(5)]
        deadline = time.monotonic() + 10
        canceled = False
        while time.monotonic() < deadline:
            jobs = [store.get(i) for i in ids]
            running = [j for j in jobs if j['status'] == 'running']
            assert len(running) <= 2
            if running and not canceled:
                store.update(running[0]['job_id'],status='canceled')
                canceled = True
            if all(j['status'] in {'succeeded','canceled'} for j in jobs):
                break
            time.sleep(.05)
        assert canceled
        assert all(store.get(i)['status'] in {'succeeded','canceled'} for i in ids)
    finally:
        queue.stop()


def test_versioned_account_daily_catchup_is_idempotent_and_stops_on_missing_bars(tmp_path, monkeypatch):
    from virtual_trading_v2 import VirtualTradingV2
    frame = bars(5)
    dates = frame.date.tolist()
    calendar = SimpleNamespace(latest_completed=lambda: dates[0], dates=lambda start,end:[d for d in dates if start <= d <= end])
    def signal(f):
        f = f.copy(); f['signal'] = 1; f['score'] = 1.; return f
    spec = SimpleNamespace(pool='core', name='fixture', requires_artifact=False, func=signal,
                           default_max_hold_days=None, default_take_profit=None, signal_type='ranking', holding_policy='hold_while_selected')
    versions = SimpleNamespace(resolve_strategy_spec=lambda key:spec, get_active_version_id=lambda key:None)
    manager = SimpleNamespace(get_stock_pool_data=lambda codes,start,end,**kwargs:(frame[frame.date<=end].copy(),{'600000':'FIXTURE'}))
    monkeypatch.setattr('virtual_trading_v2.STRATEGY_REGISTRY', {'fixture':spec})
    paper = VirtualTradingV2(manager,ExecutionDataService(None,tmp_path/'raw'),versions,{'core':['600000']},tmp_path/'paper.db',calendar)
    paper.execute_daily()
    assert paper.get_accounts()[0]['cash'] == 1000000
    calendar.latest_completed = lambda: dates[2]
    paper.execute_daily()
    trades = paper.get_trade_log()
    paper.execute_daily()
    assert paper.get_trade_log() == trades
    baseline = BacktestEngine()
    baseline.run_backtest(frame.iloc[:3],lambda *a:{'600000':1.},dates[0],dates[2])
    assert paper.get_accounts()[0]['total_value'] == baseline.portfolio.total_value
    # The next day is absent; do not write an empty day or skip ahead to later rows.
    calendar.latest_completed = lambda: dates[4]
    manager.get_stock_pool_data = lambda *a,**k:(frame[frame.date!=dates[3]].copy(),{'600000':'FIXTURE'})
    report = paper.execute_daily()
    assert report['blocked_accounts'] == 1
    assert paper.get_accounts()[0]['last_update'] == dates[2]


def test_quarantined_history_is_read_without_rewriting_archive(tmp_path):
    from data_manager import DataManager
    manager = DataManager(cache_dir=tmp_path)
    directory = tmp_path / '_removed_st_delisted'
    directory.mkdir()
    path = directory / '600000_full_history.parquet'
    frame = bars(25)
    frame.to_parquet(path)
    before = path.read_bytes()
    assert manager.get_cached_window('600000') == (frame.date.min(), frame.date.max())
    assert not manager._read_cached_frame('600000').empty
    assert path.read_bytes() == before
    assert not manager.get_cache_path('600000').exists()


def test_gem_etf_limit_uses_effective_date():
    engine = BacktestEngine()
    row = pd.Series({'stock_code':'159915','date':'2024-01-02','is_st':0})
    assert engine._limit_move_threshold(row) == .195
    row['date']='2020-08-21'
    assert engine._limit_move_threshold(row) == .095


def test_later_download_adjustment_base_does_not_change_strict_indicators(tmp_path):
    service = ExecutionDataService(None,tmp_path)
    original = bars()
    rebased = original.copy()
    rebased[['open','high','low','close']] *= .7
    a, b = service.prepare(original), service.prepare(rebased)
    pd.testing.assert_frame_equal(a[['open','high','low','close']], b[['open','high','low','close']])
