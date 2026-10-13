"""Isolated free-provider calls with hard deadlines and bounded retries."""
import contextlib
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd


class ProviderError(RuntimeError):
    pass


@contextlib.contextmanager
def cache_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def fetch_provider(provider, operation, **params):
    if os.getenv("QUANT_DATA_OFFLINE") == "1":
        raise ProviderError("离线行情模式：只读取缓存，请先补齐所需数据。")
    timeout = max(1, min(60, float(os.getenv('QUANT_PROVIDER_TIMEOUT', '20'))))
    attempts = max(1, min(3, int(os.getenv('QUANT_PROVIDER_ATTEMPTS', '2'))))
    env = os.environ.copy()
    if env.get('QUANT_DATA_BYPASS_PROXY') == '1':
        for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
            env.pop(key, None)
    error = None
    for attempt in range(attempts):
        try:
            completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'],
                input=json.dumps({'provider': provider, 'operation': operation, 'params': params}),
                text=True, capture_output=True, timeout=timeout, env=env, check=False)
            if completed.returncode:
                raise ProviderError(completed.stderr[-1500:] or f'provider exited {completed.returncode}')
            return pd.DataFrame(json.loads(completed.stdout))
        except (subprocess.TimeoutExpired, OSError, ValueError, ProviderError) as exc:
            error = exc
            if attempt + 1 < attempts:
                time.sleep(.2 * (attempt+1))
    raise ProviderError(f'{provider}/{operation} 在 {attempts} 次有限尝试后失败（单次上限 {timeout:g}s）：{error}')


def _invoke(provider, operation, params):
    if provider == 'akshare':
        import akshare as ak
        allowed = {'stock_zh_a_hist', 'fund_etf_hist_em', 'fund_etf_hist_sina', 'tool_trade_date_hist_sina'}
        if operation not in allowed:
            raise ValueError('不支持的数据接口')
        return getattr(ak, operation)(**params)
    if provider == 'baostock':
        import baostock as bs
        login = bs.login()
        if login.error_code != '0':
            raise ProviderError(login.error_msg)
        try:
            if operation == 'dividends':
                result = bs.query_dividend_data(params['symbol'], str(params['year']), 'operate')
            elif operation == 'history':
                result = bs.query_history_k_data_plus(params['symbol'],
                    'date,open,high,low,close,preclose,volume,amount,pctChg,turn,tradestatus,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST',
                    start_date=params['start'], end_date=params['end'], frequency='d', adjustflag=params.get('adjustflag', '3'))
            else:
                raise ValueError('不支持的数据接口')
            if result.error_code != '0':
                raise ProviderError(result.error_msg)
            rows = []
            while result.next():
                rows.append(result.get_row_data())
            return pd.DataFrame(rows, columns=result.fields)
        finally:
            bs.logout()
    raise ValueError('不支持的数据源')


if __name__ == '__main__':
    payload = json.load(sys.stdin)
    # Provider libraries print login messages; reserve stdout for the wire format.
    with contextlib.redirect_stdout(sys.stderr):
        value = _invoke(payload['provider'], payload['operation'], payload['params'])
    print(value.to_json(orient='records', date_format='iso'))
