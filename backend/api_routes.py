"""Read routes and lightweight cache-only terminal status."""
from fastapi import APIRouter
from research_contracts import TradingCalendar, RUNTIME_DIR, market_now


def make_read_router(api):
    router = APIRouter()
    for name, path in {'read_root': '/', 'healthz': '/healthz', 'readyz': '/readyz',
                       'get_latest': '/api/market/latest', 'get_system_status': '/api/system/status',
                       'get_strategies': '/api/strategies'}.items():
        router.add_api_route(path, getattr(api, name), methods=['GET'])

    @router.get('/api/terminal/status')
    def terminal_status():
        rows = []
        for symbol in api._latest_overview_symbols()[:12]:
            frame = api.data_manager._read_cached_frame(symbol)
            if not frame.empty:
                row = frame.sort_values('date').iloc[-1]
                rows.append({'symbol': symbol, 'name': str(row.get('stock_name', symbol)),
                    'date': str(row['date']), 'close': float(row['close']),
                    'pct_chg': float(row['pct_chg']) if api.pd.notna(row.get('pct_chg')) else None,
                    'source': '本地历史缓存'})
        target = None
        calendar_error = None
        if (RUNTIME_DIR / 'trade_calendar.json').exists():
            try:
                target = TradingCalendar().latest_completed()
            except Exception as exc:
                calendar_error = str(exc)
        else:
            calendar_error = '交易日历尚未验证，默认回测日期使用已有历史缓存截至日。'
        dates = [r['date'] for r in rows]
        latest = max(dates) if dates else None
        return {'as_of': market_now().isoformat(), 'target_date': target, 'data_as_of': latest,
                'default_end_date': target or latest, 'calendar_error': calendar_error,
                'rows': rows, 'engine_version': api.ENGINE_VERSION, 'compute_slots': 2,
                'active_jobs': len([j for j in api.job_store.list(limit=100) if j['status'] in {'queued', 'running'}])}

    return router
