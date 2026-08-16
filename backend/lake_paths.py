"""本地数据湖路径解析。

数据湖默认与仓库目录同级（例如 ~/projects/quant-viz-backtest 对应
~/projects/quant_data_lake），避免把绝对路径写死在产品代码里。
可通过环境变量 QUANT_DATA_LAKE_DIR 覆盖；若同级数据湖不存在，
回退到 backend/quant_data_lake（仓库内本地缓存）。
"""
from __future__ import annotations

import os
from pathlib import Path


def resolve_data_lake_dir() -> Path:
    env_dir = os.getenv("QUANT_DATA_LAKE_DIR")
    if env_dir:
        return Path(env_dir).expanduser()

    backend_dir = Path(__file__).resolve().parent
    sibling_dir = backend_dir.parent.parent / "quant_data_lake"
    if sibling_dir.exists():
        return sibling_dir

    return backend_dir / "quant_data_lake"
