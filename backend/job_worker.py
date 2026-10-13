"""Subprocess entrypoint: importing the API does not start its scheduler."""
import sys
import os
from job_service import JobStore


def run(store, job_id):
    os.environ['QUANT_AUTOMATION_SCHEDULER_ENABLED'] = '0'
    os.environ['QUANT_WARM_MARKET_CACHE'] = '0'
    import main
    job = store.get(job_id)
    if not job or job["status"] != "running":
        return
    try:
        request = dict(job['request'])
        replay_id = request.pop('_replay_source_job', None)
        prepared = None
        if replay_id:
            from research_metrics import load_replay_context, validate_replay_strategy
            source = store.get(replay_id)
            if not source or source['status'] != 'succeeded':
                raise ValueError('原任务不可重放')
            validate_replay_strategy(main, source['result'])
            prepared = load_replay_context(source['result']['data_snapshot_id'])
        if job["kind"] == "backtest":
            req = main.BacktestRequest(**request)
            result = main.execute_backtest(req, allow_mock=req.allow_mock, prepared=prepared)
        elif job['kind'] == 'experiment':
            from experiment_service import ExperimentRequest, run_experiment
            result = run_experiment(main, ExperimentRequest(**request), prepared=prepared)
        elif job["kind"] == "compare":
            result = main.execute_compare_request(main.CompareRequest(**job["request"]))
        elif job["kind"] == "factor_lab":
            import fcntl
            from research_contracts import RUNTIME_DIR
            with (RUNTIME_DIR / "factor_lab.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                result = main.run_factor_lab_api(main.FactorLabRunRequest(**job["request"]), main.Response())
            if hasattr(result, "status_code"):
                raise ValueError(bytes(result.body).decode())
        else:
            raise ValueError("未知任务类型")
        store.update(job_id, status="succeeded", stage="完成", result=result)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).exception("Research job failed: %s", job_id)
        store.update(job_id, status="failed", stage="失败", error=str(getattr(exc, "detail", exc)))


if __name__ == "__main__":
    run(JobStore(sys.argv[1]), sys.argv[2])
