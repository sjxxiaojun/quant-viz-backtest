from fastapi import FastAPI
import uvicorn
import pyarrow.parquet as pq
from pathlib import Path
from fastapi.responses import Response
import pandas as pd
import json

app = FastAPI()

CACHE_DIR = Path("/Users/gdxj/quant_data_lake")

@app.get("/api/v1/market/history")
def get_market_history(symbol: str):
    path = CACHE_DIR / f"{symbol}_full_history.parquet"
    if not path.exists():
        path = CACHE_DIR / "etf" / f"{symbol}_full_history.parquet"
    if not path.exists():
        return Response(status_code=404)
    with open(path, "rb") as f:
        return Response(content=f.read(), media_type="application/octet-stream")

@app.get("/api/v1/market/window")
def get_market_window(symbol: str):
    path = CACHE_DIR / f"{symbol}_full_history.parquet"
    if not path.exists():
        path = CACHE_DIR / "etf" / f"{symbol}_full_history.parquet"
    if not path.exists():
        return Response(status_code=404)
    try:
        df = pd.read_parquet(path, columns=["date"])
        start = str(df["date"].min())
        end = str(df["date"].max())
        return {"start": start, "end": end}
    except Exception:
        return Response(status_code=500)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8081)
