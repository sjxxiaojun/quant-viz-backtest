"""Research task/history and data diagnostics routes."""
import csv
import io
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, Query, Response, Request
from pydantic import BaseModel
from job_service import TERMINAL
from research_contracts import market_now


class JobView(BaseModel):
    job_id: str
    kind: str
    status: str
    stage: Optional[str] = None
    error: Optional[str] = None
    created_at: float
    updated_at: float
    request: dict


class TradesPage(BaseModel):
    items: list[dict]
    total: int
    offset: int
    limit: int


def make_router(store, queue, manager, factor_request, require_local):
    router = APIRouter()

    def find(job_id, include_result=False):
        job = store.get(job_id, include_result=include_result)
        if not job:
            raise HTTPException(404, "任务不存在")
        return job

    @router.get("/api/research/jobs", response_model=list[JobView])
    def list_jobs(kind: Optional[Literal["backtest", "compare", "factor_lab"]] = None, limit: int = Query(50, ge=1, le=100)):
        return store.list(kind, limit)

    @router.get("/api/research/jobs/{job_id}", response_model=JobView)
    def status(job_id: str):
        return find(job_id)

    @router.post("/api/research/jobs/{job_id}/cancel")
    def cancel(job_id: str, request: Request):
        require_local(request)
        job = find(job_id)
        if job["status"] not in TERMINAL:
            store.update(job_id, status="canceled", stage="已取消")
        return {"job_id": job_id, "status": store.get(job_id)["status"]}

    @router.get("/api/research/jobs/{job_id}/result")
    def result(job_id: str):
        job = find(job_id, include_result=True)
        if job["status"] != "succeeded":
            raise HTTPException(425 if job["status"] not in TERMINAL else 409, job["error"] or job["status"])
        return job["result"]

    def trade_rows(value, strategy=None):
        if strategy:
            return value.get(strategy, {}).get("trades", [])
        if "backtest" in value:
            return (value.get("backtest") or {}).get("trades", [])
        if "trades" in value:
            return value["trades"]
        return [{**row, "strategy": key} for key,item in value.items() if isinstance(item,dict) for row in item.get("trades", [])]

    @router.get("/api/research/jobs/{job_id}/trades", response_model=TradesPage)
    def trades(job_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=1000), strategy: Optional[str] = None):
        value = result(job_id)
        rows = trade_rows(value, strategy)
        return {"items": rows[offset:offset+limit], "total": len(rows), "offset": offset, "limit": limit}

    @router.get("/api/research/jobs/{job_id}/trades.csv")
    def export(job_id: str, strategy: Optional[str] = None):
        value = result(job_id)
        rows = trade_rows(value, strategy)
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=sorted({k for row in rows for k in row}))
            writer.writeheader()
            for row in rows:
                writer.writerow({k: ("'"+v if isinstance(v,str) and v[:1] in "=+-@" else v) for k,v in row.items()})
        return Response(output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="trades-{job_id}.csv"'})

    @router.post("/api/factor-lab/jobs")
    def factor_job(payload: dict, request: Request):
        require_local(request)
        req = factor_request(**payload)
        try:
            job_id = queue.submit("factor_lab", req.model_dump())
        except ValueError as exc:
            raise HTTPException(429, str(exc))
        return {"job_id": job_id}

    @router.get("/api/data/diagnostics")
    def data_diagnostics():
        from research_contracts import TradingCalendar, RUNTIME_DIR
        from pathlib import Path
        import pandas as pd
        groups = {}
        try:
            target = TradingCalendar().latest_completed()
            calendar_error = None
        except Exception as exc:
            target = None
            calendar_error = str(exc)
        for kind in ("a_share", "etf"):
            codes = manager.list_local_codes(kind)
            sample = codes[::max(1, len(codes)//30)][:30]
            dates = []
            missing = []
            for code in sample:
                try:
                    frame = pd.read_parquet(manager.get_cache_path(code), columns=["date"])
                    date = str(frame.date.max())
                    dates.append(date)
                    if target and date < target:
                        missing.append(code)
                except Exception:
                    missing.append(code)
            groups[kind] = {"total_local": len(codes), "checked_count": len(sample), "fresh_count": len(sample)-len(missing) if target else None,
                            "sample_latest_date": max(dates) if dates else None, "sample_oldest_date": min(dates) if dates else None, "stale_symbols_sample": missing,
                            "is_sample": True, "raw_cached_symbols": len(list((RUNTIME_DIR / "raw").glob("*.parquet")))}
        return {"as_of": market_now().isoformat(), "target_date": target, "calendar_error": calendar_error, "groups": groups,
                "note": "覆盖率为最多30只的确定性抽样；实际运行对所选标的逐日校验。"}

    return router
