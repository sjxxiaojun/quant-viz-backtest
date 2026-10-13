import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import main
import data_provider
import research_contracts
from api_models import BacktestRequest
from experiment_service import ExperimentRequest, run_experiment
from factor_lab.causal import generate_predictions
from job_service import JobQueue, JobStore
from research_assistant import analyze
from research_contracts import ExecutionDataService
from research_metrics import metric_view


def request():
    return BacktestRequest(start_date='2024-01-01', end_date='2024-12-31', initial_capital=1000000,
                           factor='turtle', stocks=['000001'], pool='custom')


def test_new_service_key_does_not_accept_model_credential(monkeypatch):
    monkeypatch.setenv('QUANT_API_KEY', 'service-only')
    monkeypatch.setenv('QUANT_AI_MODEL_API_KEY', 'model-only')
    monkeypatch.setenv('QUANT_AI_API_KEY', 'old-key')
    from starlette.requests import Request
    def req(value):
        return Request({'type': 'http', 'headers': [(b'x-quant-api-key', value.encode())]})
    assert main._has_valid_quant_api_key(req('service-only'))
    assert not main._has_valid_quant_api_key(req('model-only'))
    assert not main._has_valid_quant_api_key(req('old-key'))


@pytest.mark.parametrize('start,end', [('2024-02-30','2024-12-31'), ('20240101','2024-12-31'), ('2024-12-31','2024-01-01')])
def test_dates_are_valid_and_ordered(start,end):
    with pytest.raises(ValidationError):
        BacktestRequest(**{**request().model_dump(), 'start_date': start, 'end_date': end})


def test_parameter_budget_and_arbitrary_changes_rejected():
    with pytest.raises(ValidationError):
        ExperimentRequest(base=request(), candidates=[{}]*13)
    with pytest.raises(ValidationError):
        ExperimentRequest(base=request(), candidates=[{'price_mode': 'approximate_adjusted'}])


def test_test_period_cannot_select_parameter_winner():
    dates = pd.bdate_range('2024-01-01', periods=100).strftime('%Y-%m-%d')
    frame = pd.DataFrame({'date':dates,'close':np.arange(100.)})
    calls = []
    def execute(req, **kwargs):
        supplied = kwargs['prepared']['frame']
        calls.append((req, supplied.copy()))
        # Reverse the ranking in the holdout. It must never select the winner.
        net = -.1 if req.stop_loss == -.05 else -.2
        if req.start_date == dates[80]:
            net = -.9 if req.stop_loss == -.05 else .9
        return {'total_return':net, 'history':[], 'trades':[], 'summary':{'max_drawdown':-.2},
                'provenance':{}, 'metrics':{'net_return':net,'max_drawdown':-.2}}
    api = SimpleNamespace(strategy_version_store=SimpleNamespace(resolve_strategy_spec=lambda _:SimpleNamespace(requires_artifact=False), get_active_version_id=lambda _:None,get_version=lambda _:None), execute_backtest=execute)
    market = {'frame':frame,'snapshot_id':'f'*64}
    result = run_experiment(api, ExperimentRequest(base=request(), candidates=[{'stop_loss':-.05},{'stop_loss':-.1}]), prepared=market)
    assert result['winner_candidate_id'] == 0
    assert result['test_result']['total_return'] == -.9
    assert len(calls) == 3
    assert all(f.date.max() == dates[79] for _,f in calls[:2])
    assert calls[-1][0].start_date == dates[80]


def test_provider_timeout_is_bounded_and_does_not_change_parent_environment(monkeypatch):
    monkeypatch.delenv('QUANT_DATA_OFFLINE',raising=False)
    calls = []
    monkeypatch.setenv('QUANT_PROVIDER_TIMEOUT','1')
    monkeypatch.setenv('QUANT_PROVIDER_ATTEMPTS','2')
    monkeypatch.setenv('HTTPS_PROXY','http://example.invalid')
    monkeypatch.setenv('QUANT_DATA_BYPASS_PROXY','1')
    def timeout(*args,**kwargs):
        calls.append(kwargs)
        raise subprocess.TimeoutExpired('provider',1)
    monkeypatch.setattr(data_provider.subprocess,'run',timeout)
    with pytest.raises(data_provider.ProviderError, match='2 次'):
        data_provider.fetch_provider('akshare','stock_zh_a_hist',symbol='000001')
    assert len(calls)==2 and all(c['timeout']==1 for c in calls)
    assert all('HTTPS_PROXY' not in c['env'] for c in calls)
    import os
    assert os.environ['HTTPS_PROXY']=='http://example.invalid'


def test_current_year_company_action_refresh_deduplicates(tmp_path,monkeypatch):
    monkeypatch.setattr(research_contracts,'market_now',lambda:datetime(2026,10,13))
    row={'dividOperateDate':'2026-06-01','dividCashPsBeforeTax':'0.2','dividStocksPs':'0',
         'dividReserveToStockPs':'0','dividPayDate':'2026-06-02','dividStockMarketDate':''}
    monkeypatch.setattr(research_contracts,'fetch_provider',lambda *a,**k:pd.DataFrame([row]))
    service=ExecutionDataService(SimpleNamespace(),tmp_path)
    first=service._load_actions('600000',{2026})
    path=tmp_path/'actions/600000.json'
    cached=json.loads(path.read_text());cached['checked_at']=0;path.write_text(json.dumps(cached))
    second=service._load_actions('600000',{2026})
    assert first==second and len(second)==1


def test_concurrent_raw_cache_updates_preserve_both_ranges(tmp_path,monkeypatch):
    def fetch(provider,operation,**params):
        dates=pd.date_range(pd.Timestamp(params['start_date']),pd.Timestamp(params['end_date'])).strftime('%Y-%m-%d')
        time.sleep(.05)
        return pd.DataFrame({'date':dates,'open':10.,'high':10.,'low':10.,'close':10.,'pct_chg':0.})
    monkeypatch.setattr(research_contracts,'fetch_provider',fetch)
    service=ExecutionDataService(SimpleNamespace(is_etf_symbol=lambda _:True),tmp_path)
    with ThreadPoolExecutor(2) as pool:
        futures=[pool.submit(service._load_raw,'518880',a,b) for a,b in [('2024-01-01','2024-01-03'),('2024-01-04','2024-01-06')]]
        for f in futures: f.result()
    assert len(pd.read_parquet(tmp_path/'518880.parquet'))==6


def test_queue_spawn_failure_does_not_kill_coordinators(tmp_path,monkeypatch):
    store=JobStore(tmp_path/'jobs.db');queue=JobQueue(store)
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k: (_ for _ in ()).throw(OSError('spawn failed')))
    try:
        ids=[queue.submit('backtest',{}) for _ in range(3)]
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and any(store.get(i)['status']!='failed' for i in ids): time.sleep(.02)
        assert all(store.get(i)['status']=='failed' for i in ids)
        assert all(t.is_alive() for t in queue.threads)
    finally: queue.stop()


def test_duplicate_queue_owner_cannot_interrupt_running_jobs(tmp_path):
    store=JobStore(tmp_path/'jobs.db');first=JobQueue(store);second=JobQueue(store)
    try:
        first.start()
        with pytest.raises(RuntimeError,match='已有计算队列'): second.start()
        assert len(first.threads)==2
    finally: first.stop()
    second.start();second.stop()


def test_optional_model_ignores_later_features_and_labels():
    dates=pd.bdate_range('2023-01-01',periods=181).strftime('%Y-%m-%d')
    features=[f'f{i}' for i in range(5)];rng=np.random.default_rng(11)
    rows=[{'date':date,'stock_code':str(code),'label_end_date':dates[min(i+5,180)],
           'label_reg':rng.normal(),'split':'test',**dict(zip(features,rng.normal(size=5)))}
          for i,date in enumerate(dates) for code in range(5)]
    frame=pd.DataFrame(rows)
    first=generate_predictions(frame,features,11,max_windows=1,rf_n_estimators=4,enable_hist_gradient_boosting=True)
    changed=frame.copy();changed.loc[changed.date>dates[179],features+['label_reg']]=1000
    second=generate_predictions(changed,features,11,max_windows=1,rf_n_estimators=4,enable_hist_gradient_boosting=True)
    pd.testing.assert_series_equal(first['scored'].walk_forward_composite_score,second['scored'].walk_forward_composite_score)
    assert first['summary']['folds'][0]['model_recipe']['nonlinear_v2_model']=='hist_gradient_boosting'


def test_no_oos_window_is_explicit():
    result=generate_predictions(pd.DataFrame({'date':['2024-01-01'],'stock_code':['000001']}),[],42)
    assert result['summary']['enabled'] is False
    assert '无法完成样本外评估' in result['summary']['message']


def saved_job():
    return {'job_id':'selected','kind':'backtest','request':request().model_dump(),
        'result':{'total_return':.1,'summary':{'max_drawdown':-.2},'history':[], 'quality_notes':['冻结行情']}}


def test_local_analysis_never_calls_model(monkeypatch):
    monkeypatch.setenv('QUANT_AI_ENDPOINT','https://example.invalid')
    response=analyze([saved_job()],SimpleNamespace(_post_json=lambda *a:pytest.fail('model called')),False)
    assert response.source=='local' and response.proposals==[]


@pytest.mark.parametrize('raw',['not-json',json.dumps({'summary':'x','observations':[],'proposals':[{'job_id':'unselected','changes':{},'reason':'x'}]}),json.dumps({'summary':'x','actions':[{'type':'execute_virtual_trade'}]})])
def test_bad_or_actionable_model_output_returns_local_fallback(raw,monkeypatch):
    monkeypatch.setenv('QUANT_AI_ENDPOINT','https://example.invalid')
    monkeypatch.setenv('QUANT_AI_OPENAI_COMPATIBLE','0')
    response=analyze([saved_job()],SimpleNamespace(_post_json=lambda *a:raw),True)
    assert response.source=='local_fallback' and response.proposals==[]


def test_missing_benchmark_is_not_zero_excess_return():
    metric=metric_view({'total_return':.1,'summary':{'benchmark_return':0,'excess_return':.1}})
    assert metric['benchmark_return'] is None and metric['excess_return'] is None


def test_verified_raw_research_is_independent_of_mixed_legacy_adjustment_rows(tmp_path, monkeypatch):
    from test_reliable_v2 import bars
    manager = SimpleNamespace(is_etf_symbol=lambda _:False)
    service = ExecutionDataService(manager,tmp_path)
    monkeypatch.setattr(service,'_load_actions',lambda *a:[])
    original=bars()
    changed=original.copy();changed.loc[4,'close']*=.91
    first=service.prepare(original);second=service.prepare(changed)
    pd.testing.assert_series_equal(first.close,second.close)
    # An unexplained change in the raw ex-dividend reference must still block.
    changed.loc[4,'raw_prev_close']*=.9
    with pytest.raises(research_contracts.DataContractError,match='参考价'):
        service.prepare(changed)


def test_replay_checks_market_and_benchmark_integrity(tmp_path, monkeypatch):
    import research_metrics
    from research_contracts import persist_snapshot
    from test_reliable_v2 import bars
    monkeypatch.setattr(research_metrics,'RUNTIME_DIR',tmp_path)
    frame=bars()
    benchmark=pd.DataFrame({'date':frame.date,'close':np.arange(len(frame))+100.})
    sid=persist_snapshot(frame,{}, {},tmp_path/'snapshots')
    research_metrics.save_replay_context(sid,['600000'],{},frame.date.min(),{},benchmark)
    loaded=research_metrics.load_replay_context(sid)
    pd.testing.assert_frame_equal(loaded['frame'],frame)
    changed=benchmark.copy();changed.loc[0,'close']=500
    changed.to_parquet(tmp_path/f'snapshots/{sid}.benchmark.parquet',index=False)
    with pytest.raises(ValueError,match='基准快照'):
        research_metrics.load_replay_context(sid)

    benchmark.to_parquet(tmp_path/f'snapshots/{sid}.benchmark.parquet',index=False)
    changed=frame.copy();changed.loc[0,'raw_close']=500
    changed.to_parquet(tmp_path/f'snapshots/{sid}.parquet',index=False)
    with pytest.raises(ValueError,match='行情快照'):
        research_metrics.load_replay_context(sid)


def test_new_code_run_does_not_reuse_old_replay_credentials(tmp_path,monkeypatch):
    import experiment_service
    import research_metrics
    from test_reliable_v2 import bars
    from research_contracts import persist_snapshot
    frame=bars()
    api=SimpleNamespace(BACKTEST_MAX_ROWS=1000000,prepare_backtest_universe=lambda req:(['600000'],{},frame.date.min()),
        data_manager=SimpleNamespace(get_stock_pool_data=lambda *a,**k:(frame.copy(),{}),get_stock_data=lambda *a,**k:(pd.DataFrame(),'')),
        execution_data_service=SimpleNamespace(prepare=lambda df,**k:df))
    monkeypatch.setattr(research_metrics,'RUNTIME_DIR',tmp_path)
    monkeypatch.setattr(experiment_service,'persist_snapshot',lambda f,r,u:persist_snapshot(f,r,u,tmp_path/'snapshots'))
    monkeypatch.setattr(experiment_service,'code_fingerprint',lambda:'old-code')
    monkeypatch.setattr(research_metrics,'code_fingerprint',lambda:'old-code')
    old=experiment_service.freeze_market(api,request())
    monkeypatch.setattr(experiment_service,'code_fingerprint',lambda:'new-code')
    monkeypatch.setattr(research_metrics,'code_fingerprint',lambda:'new-code')
    new=experiment_service.freeze_market(api,request())
    assert old['snapshot_id']!=new['snapshot_id']
    with pytest.raises(ValueError,match='代码版本'):
        research_metrics.load_replay_context(old['snapshot_id'])
    pd.testing.assert_frame_equal(research_metrics.load_replay_context(new['snapshot_id'])['frame'],frame)


def test_account_migration_preserves_old_ledger_and_takes_backup(tmp_path):
    import sqlite3
    from scripts.migrate_account_engine import migrate
    path=tmp_path/'accounts.db'
    old=json.dumps({'cash':12345,'positions':{'000001':{'quantity':100}},'history':[{'date':'2024-01-01'}]})
    current=json.dumps({'engine_version':'daily-v3','cash':50000})
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE accounts_v2 (strategy_id TEXT PRIMARY KEY,name TEXT,state TEXT)')
        conn.executemany('INSERT INTO accounts_v2 VALUES (?,?,?)',[('old','旧账户',old),('current','新账户',current)])
    assert migrate(path)['legacy_count']==1
    result=migrate(path,apply=True)
    with sqlite3.connect(path) as conn:
        rows=conn.execute('SELECT strategy_id,state FROM accounts_v2').fetchall()
    assert ('current',current) in rows
    assert any(key.startswith('old@engine-archive@') and state==old for key,state in rows)
    with sqlite3.connect(result['backup']) as conn:
        assert conn.execute('SELECT state FROM accounts_v2 WHERE strategy_id="old"').fetchone()[0]==old


def test_new_mutation_routes_block_nonlocal_requests_before_work(monkeypatch):
    client=TestClient(main.app,client=('203.0.113.7',1234))
    monkeypatch.setattr(main.job_queue,'submit',lambda *a:pytest.fail('job submitted'))
    assert client.post('/api/experiments/jobs',json={'base':request().model_dump(),'candidates':[{}]}).status_code==403
    assert client.post('/api/research/analysis',json={'job_ids':['selected']}).status_code==403
    assert client.post('/api/research/jobs/selected/replay').status_code==403
