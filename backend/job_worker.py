"""Subprocess entrypoint: importing the API does not start its scheduler."""
import sys
from job_service import JobStore


def run(store, job_id):
    import main
    job = store.get(job_id)
    if not job or job["status"] != "running":
        return
    try:
        if job["kind"] == "backtest":
            req = main.BacktestRequest(**job["request"])
            result = main.execute_backtest(req, allow_mock=req.allow_mock)
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
