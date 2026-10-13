"""Comparable metrics and reproducibility metadata for saved experiments."""
import hashlib
import json
import platform
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from importlib.metadata import version

from research_contracts import RUNTIME_DIR, atomic_json, snapshot_fingerprint
from data_provider import cache_lock
import uuid


@lru_cache(maxsize=1)
def code_fingerprint():
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(root.glob('*.py')) + sorted((root / 'strategies').glob('*.py')) + sorted((root / 'factor_lab').glob('*.py')):
        if path.name.startswith(('test_', 'conftest')):
            continue
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    digest.update((root / 'uv.lock').read_bytes())
    return digest.hexdigest()


def metric_view(result):
    summary = result.get('summary', {})
    costs = summary.get('cost_stats', {})
    benchmark = summary.get('benchmark_return') if result.get('benchmark_history') else None
    return {
        'net_return': result.get('total_return'),
        'benchmark_return': benchmark,
        'excess_return': summary.get('excess_return') if benchmark is not None else None,
        'max_drawdown': summary.get('max_drawdown'),
        'sharpe_ratio': summary.get('sharpe_ratio'),
        'turnover_ratio': costs.get('turnover_ratio'),
        'total_cost': costs.get('total_cost'),
        'trade_count': len(result.get('trades', [])),
    }


def enrich_result(result, request, snapshot_id):
    result['metrics'] = metric_view(result)
    result['provenance'] = {
        'code_fingerprint': code_fingerprint(), 'data_snapshot_id': snapshot_id,
        'parameters': request.model_dump(), 'seed': 42,
        'python': platform.python_version(), 'numpy': np.__version__,
        'pandas': pd.__version__, 'scikit_learn': version('scikit-learn'),
    }


def runtime_versions():
    return {'python': platform.python_version(),
            **{name: version(name) for name in ('numpy', 'pandas', 'scipy', 'scikit-learn', 'pyarrow')}}


def strategy_identity(store, factor, spec):
    version_id = store.get_active_version_id(factor)
    pinned = store.get_version(version_id or factor)
    artifact_hash = None
    if spec.requires_artifact:
        from strategy_versioning import artifact_fingerprint
        from factor_lab.strategy import REPORT_ROOT
        artifact_hash = artifact_fingerprint(str(pinned['artifact_ref'] if pinned else REPORT_ROOT))['artifact_hash']
    return {'strategy_id': factor, 'version_id': version_id or (factor if pinned else None), 'artifact_hash': artifact_hash}


def validate_replay_strategy(api, value):
    result = value.get('test_result', value)
    saved = result.get('provenance', {}).get('strategy')
    if not saved:
        raise ValueError('旧结果缺少策略版本凭证，请新建实验。')
    spec = api.strategy_version_store.resolve_strategy_spec(saved['strategy_id'])
    if spec is None or strategy_identity(api.strategy_version_store, saved['strategy_id'], spec) != saved:
        raise ValueError('策略版本或模型产物已变化，拒绝将新策略作为原结果重放。')


def save_replay_context(snapshot_id, symbols, universe, warmup_start, sources, benchmark):
    root = RUNTIME_DIR / 'snapshots'
    path = root / f'{snapshot_id}.replay.json'
    with cache_lock(path):
        if path.exists():
            return
        if benchmark is not None and not benchmark.empty:
            tmp = root / f'{snapshot_id}.{uuid.uuid4().hex}.benchmark.tmp.parquet'
            benchmark.to_parquet(tmp, index=False)
            tmp.replace(root / f'{snapshot_id}.benchmark.parquet')
        atomic_json(path, {'symbols': symbols, 'universe': universe, 'warmup_start': warmup_start,
                          'sources': sources, 'code_fingerprint': code_fingerprint(),
                          'runtime_versions': runtime_versions(),
                          'benchmark_fingerprint': snapshot_fingerprint(benchmark, {})})


def load_replay_context(snapshot_id):
    if len(snapshot_id) != 64 or any(c not in '0123456789abcdef' for c in snapshot_id):
        raise ValueError('无效数据快照标识')
    root = RUNTIME_DIR / 'snapshots'
    meta = json.loads((root / f'{snapshot_id}.replay.json').read_text())
    if meta['code_fingerprint'] != code_fingerprint():
        raise ValueError('代码版本已变化；请使用原版本重放，或新建实验比较差异。')
    if meta.get('runtime_versions') != runtime_versions():
        raise ValueError('计算环境版本已变化，请在原锁定环境中重放。')
    meta['frame'] = pd.read_parquet(root / f'{snapshot_id}.parquet')
    manifest = json.loads((root / f'{snapshot_id}.json').read_text())
    if snapshot_fingerprint(meta['frame'], manifest) != snapshot_id:
        raise ValueError('行情快照完整性校验失败，拒绝重放。')
    benchmark = root / f'{snapshot_id}.benchmark.parquet'
    meta['benchmark'] = pd.read_parquet(benchmark) if benchmark.exists() else None
    if snapshot_fingerprint(meta['benchmark'], {}) != meta.get('benchmark_fingerprint', 'unavailable'):
        raise ValueError('基准快照完整性校验失败，拒绝重放。')
    meta['snapshot_id'] = snapshot_id
    return meta
