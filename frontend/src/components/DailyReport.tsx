import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Newspaper, RefreshCw, Star, TrendingDown, TrendingUp } from 'lucide-react';
import { apiGet, apiPost, getApiErrorMessage, isRequestCanceled } from '../api/client';
import { changeToneClass, cn, formatNumber, formatPercent } from '../utils';
import { EmptyState, Panel, SectionTitle, Skeleton, Stat, Tag } from './ui';

interface Recommendation {
  rank: number;
  stock_code: string;
  stock_name: string;
  score: number;
  signal: number;
  held: boolean;
  holding_strategies: string[];
  recommendation: string;
  current_price?: number | null;
  pct_chg?: number | null;
  change_amount?: number | null;
}

interface FactorStatus {
  run_id: string;
  best_factor: string;
  test_rank_ic: number;
  test_top20_ret: number;
  model_recipe: {
    baseline_model: string;
    nonlinear_model: string;
    baseline_weight: number;
    nonlinear_weight: number;
  };
  generated_at: string;
}

interface MarketOverview {
  date: string;
  total_stocks: number;
  signal_count: number;
  avg_score: number;
}

interface DailyReportData {
  report_date: string;
  generated_at: string;
  market_overview: MarketOverview;
  factor_status: FactorStatus;
  recommendations: Recommendation[];
  risk_warnings: string[];
  /** 后端 GET /api/daily-report/latest 只读返回缓存, 用该字段标记缓存是否过期 */
  stale?: boolean;
  /** 过期原因代码, 与 backend/main.py:_daily_report_staleness 一一对应 */
  stale_reasons?: string[];
}

const HEADER_CELL = 'label-caps px-3 py-2 whitespace-nowrap';
const CELL = 'px-3 py-1.5 whitespace-nowrap';

/** 过期原因代码 -> 人话。代码来源: backend/main.py `_daily_report_staleness()` */
const STALE_REASON_LABELS: Record<string, string> = {
  missing_current_price: '推荐标的缺少最新价，行情数据尚未回填',
  missing_stock_name: '推荐标的缺少股票名称，标的元数据不完整',
  report_date_outdated: '报告日期已落后于当前日期，不是最新一期晨报',
};

function staleReasonLabel(code: string): string {
  return STALE_REASON_LABELS[code] ?? `未知过期原因（${code}）`;
}

export function DailyReport() {
  const [report, setReport] = useState<DailyReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const mountedRef = useRef(false);
  const requestRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  // 只负责取数; 加载态/错误态的"进入"由调用方决定:
  // 首屏靠 loading 的初始值 true(挂载 effect 内同步 setState 会多触发一轮渲染),
  // 手动刷新走下面的 refreshReport。
  const fetchReport = useCallback(async () => {
    const requestId = ++requestRef.current;
    try {
      const data = await apiGet<DailyReportData>('/api/daily-report/latest', {
        signal: abortRef.current?.signal,
      });
      if (!mountedRef.current || requestId !== requestRef.current) return;
      setReport(data);
      setError(null);
    } catch (err: unknown) {
      if (isRequestCanceled(err)) return;
      if (!mountedRef.current || requestId !== requestRef.current) return;
      setError(getApiErrorMessage(err, '获取晨报失败'));
    } finally {
      if (mountedRef.current && requestId === requestRef.current) {
        setLoading(false);
      }
    }
  }, []);

  const refreshReport = useCallback(async () => {
    setLoading(true);
    setError(null);
    await fetchReport();
  }, [fetchReport]);

  // 重新生成一律走 POST /api/daily-report/generate。
  // GET /api/daily-report/latest 已改为只读缓存(regenerate=true 属 deprecated 兼容路径),
  // 不会再自动重生成, 所以过期只能由用户在这里显式触发。
  const generateReport = async () => {
    setGenerating(true);
    try {
      await apiPost('/api/daily-report/generate', undefined, {
        timeout: 300000,
        signal: abortRef.current?.signal,
      });
      if (!mountedRef.current) return;
      await refreshReport();
    } catch (err: unknown) {
      if (isRequestCanceled(err)) return;
      if (!mountedRef.current) return;
      setError(getApiErrorMessage(err, '生成晨报失败'));
    } finally {
      if (mountedRef.current) {
        setGenerating(false);
      }
    }
  };

  useEffect(() => {
    mountedRef.current = true;
    abortRef.current = new AbortController();
    void fetchReport();
    return () => {
      mountedRef.current = false;
      requestRef.current += 1;
      abortRef.current?.abort();
    };
  }, [fetchReport]);

  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-9 w-64" />
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  // 已经有报告内容时不整屏顶掉(否则重新生成失败会把过期提示一起弄丢),
  // 错误改为在报告上方以横条展示。
  if (error && !report) {
    return (
      <div className="space-y-3">
        <div className="rounded-panel border border-up/30 bg-up/10 px-4 py-3 text-xs text-up-soft">
          {error}
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => void refreshReport()}
            className="rounded-ctl bg-accent px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-accent/85"
          >
            重试
          </button>
          <button
            type="button"
            onClick={() => void generateReport()}
            disabled={generating}
            className="rounded-ctl border border-line bg-bg2 px-3 py-1.5 text-xs font-semibold text-slate-200 transition-colors hover:bg-bg3 disabled:opacity-50"
          >
            {generating ? '生成中...' : '生成新晨报'}
          </button>
        </div>
      </div>
    );
  }

  if (!report) {
    return (
      <EmptyState
        icon={<Newspaper className="h-6 w-6" />}
        title="暂无晨报数据"
        description="生成后展示市场概览、因子状态与 Top 10 推荐。"
        action={
          <button
            type="button"
            onClick={() => void generateReport()}
            disabled={generating}
            className="rounded-ctl bg-accent px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-accent/85 disabled:opacity-50"
          >
            {generating ? '生成中...' : '生成今日晨报'}
          </button>
        }
      />
    );
  }

  const staleReasons = report.stale_reasons ?? [];
  const isStale = report.stale === true || staleReasons.length > 0;

  return (
    <div className="space-y-3">
      {error && (
        <div className="rounded-panel border border-up/30 bg-up/10 px-4 py-2.5 text-xs text-up-soft">
          {error}
        </div>
      )}

      {/* 缓存过期提示: 后端 GET 只读返回缓存, 不再自动重生成, 必须显式告知用户 */}
      {isStale && (
        <Panel className="border-warn/40 bg-warn/5">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-warn">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <span className="text-sm font-semibold">当前晨报已过期</span>
              </div>
              <p className="mt-1 text-xs text-slate-300">
                下方内容来自缓存文件，接口不会自动重新生成；请点击右侧按钮手动重新生成后再据此决策。
              </p>
              {staleReasons.length > 0 ? (
                <ul className="mt-2 space-y-1">
                  {staleReasons.map((reason) => (
                    <li key={reason} className="flex items-start gap-2 text-xs text-slate-300">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-warn" />
                      <span>
                        {staleReasonLabel(reason)}
                        <span className="num ml-1.5 text-[10px] text-slate-500">({reason})</span>
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-xs text-slate-400">后端未给出具体过期原因。</p>
              )}
            </div>
            <button
              type="button"
              onClick={() => void generateReport()}
              disabled={generating}
              className="inline-flex shrink-0 items-center gap-1.5 self-start rounded-ctl border border-warn/50 bg-warn/15 px-3 py-1.5 text-xs font-semibold text-warn transition-colors hover:bg-warn/25 disabled:opacity-50"
            >
              {generating ? (
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-warn/30 border-t-warn" />
              ) : (
                <RefreshCw className="h-3 w-3" />
              )}
              {generating ? '重新生成中...' : '立即重新生成'}
            </button>
          </div>
        </Panel>
      )}

      {/* 头部 */}
      <Panel className="flex flex-col justify-between gap-3 md:flex-row md:items-center">
        <div>
          <div className="flex items-center gap-2">
            <Newspaper className="h-4 w-4 text-accent" />
            <h2 className="text-base font-semibold text-slate-100">量化晨报</h2>
            {isStale ? (
              <Tag tone="warn" title={staleReasons.map(staleReasonLabel).join('；')}>
                <AlertTriangle className="h-2.5 w-2.5" />
                已过期
              </Tag>
            ) : (
              <Tag tone="ok">最新</Tag>
            )}
          </div>
          <p className="num mt-1 text-[11px] text-slate-500">
            {report.report_date} · 生成时间 {new Date(report.generated_at).toLocaleString('zh-CN')}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={() => void refreshReport()}
            className="inline-flex items-center gap-1.5 rounded-ctl border border-line bg-bg2 px-3 py-1.5 text-xs font-semibold text-slate-300 transition-colors hover:bg-bg3 hover:text-slate-100"
          >
            <RefreshCw className="h-3 w-3" /> 刷新
          </button>
          <button
            type="button"
            onClick={() => void generateReport()}
            disabled={generating}
            className="inline-flex items-center gap-1.5 rounded-ctl bg-accent px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-accent/85 disabled:opacity-50"
          >
            {generating ? (
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white" />
            ) : (
              <Newspaper className="h-3 w-3" />
            )}
            {generating ? '生成中...' : '生成新晨报'}
          </button>
        </div>
      </Panel>

      {/* 市场概览 */}
      <Panel className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="股票总数" value={formatNumber(report.market_overview.total_stocks, 0)} />
        <Stat label="信号股票" value={formatNumber(report.market_overview.signal_count, 0)} />
        <Stat label="平均分数" value={report.market_overview.avg_score.toFixed(4)} />
        <Stat label="Test RankIC" value={report.factor_status.test_rank_ic.toFixed(4)} />
      </Panel>

      {/* 因子状态 */}
      <Panel>
        <SectionTitle>因子状态</SectionTitle>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div>
            <div className="label-caps">最佳因子</div>
            <div className="mt-0.5 text-sm font-semibold text-slate-100">
              {report.factor_status.best_factor}
            </div>
          </div>
          <div>
            <div className="label-caps">Test Top20 收益</div>
            <div
              className={cn(
                'num mt-0.5 text-sm font-semibold',
                changeToneClass(report.factor_status.test_top20_ret),
              )}
            >
              {formatPercent(report.factor_status.test_top20_ret, { signed: true })}
            </div>
          </div>
          <div>
            <div className="label-caps">模型融合</div>
            <div className="num mt-0.5 text-sm font-semibold text-slate-100">
              {report.factor_status.model_recipe.baseline_model}{' '}
              {Math.round(report.factor_status.model_recipe.baseline_weight * 100)}% +{' '}
              {report.factor_status.model_recipe.nonlinear_model}{' '}
              {Math.round(report.factor_status.model_recipe.nonlinear_weight * 100)}%
            </div>
          </div>
        </div>
      </Panel>

      {/* Top 10 推荐 */}
      <Panel padded={false} className="overflow-hidden">
        <div className="border-b border-line px-3 py-2">
          <span className="label-caps">今日 Top 10 推荐</span>
        </div>
        {report.recommendations.length ? (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-xs">
              <thead>
                <tr className="border-b border-line bg-bg2">
                  <th className={HEADER_CELL}>排名</th>
                  <th className={HEADER_CELL}>代码</th>
                  <th className={HEADER_CELL}>名称</th>
                  <th className={cn(HEADER_CELL, 'text-right')}>最新价</th>
                  <th className={cn(HEADER_CELL, 'text-right')}>涨跌幅</th>
                  <th className={cn(HEADER_CELL, 'text-right')}>分数</th>
                  <th className={HEADER_CELL}>信号</th>
                  <th className={HEADER_CELL}>持仓</th>
                  <th className={HEADER_CELL}>建议</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {report.recommendations.map((rec) => (
                  <tr key={rec.rank} className="transition-colors hover:bg-bg2">
                    <td className={cn(CELL, 'num', rec.rank <= 3 ? 'font-semibold text-accent' : 'text-slate-400')}>
                      {rec.rank}
                    </td>
                    <td className={cn(CELL, 'num text-slate-300')}>{rec.stock_code}</td>
                    <td className={cn(CELL, 'font-medium text-slate-100')}>{rec.stock_name}</td>
                    <td className={cn(CELL, 'num text-right text-slate-200')}>
                      {rec.current_price != null ? `¥${formatNumber(rec.current_price)}` : '--'}
                    </td>
                    <td className={cn(CELL, 'text-right')}>
                      {rec.pct_chg != null ? (
                        // A股语义: 红涨绿跌 (pct_chg 为百分数口径)
                        <span
                          className={cn(
                            'num inline-flex items-center justify-end gap-1 font-medium',
                            changeToneClass(rec.pct_chg),
                          )}
                        >
                          {rec.pct_chg > 0 ? (
                            <TrendingUp className="h-3 w-3" />
                          ) : rec.pct_chg < 0 ? (
                            <TrendingDown className="h-3 w-3" />
                          ) : null}
                          {formatPercent(rec.pct_chg, { from: 'percent', signed: true })}
                        </span>
                      ) : (
                        <span className="text-slate-500">--</span>
                      )}
                    </td>
                    <td
                      className={cn(
                        CELL,
                        'num text-right font-medium',
                        rec.score >= 0.9 ? 'text-ok' : rec.score >= 0.7 ? 'text-accent' : 'text-slate-400',
                      )}
                    >
                      {rec.score.toFixed(4)}
                    </td>
                    <td className={CELL}>
                      {/* 买入信号按 A股动作语义标红 */}
                      {rec.signal === 1 ? <Tag tone="up">买入</Tag> : <Tag>观察</Tag>}
                    </td>
                    <td className={CELL}>
                      {rec.held ? (
                        <Tag tone="warn" title={rec.holding_strategies.join(', ')}>
                          <Star className="h-2.5 w-2.5" />
                          {rec.holding_strategies.join(', ')}
                        </Tag>
                      ) : (
                        <span className="text-[10px] text-slate-500">未持仓</span>
                      )}
                    </td>
                    <td className={CELL}>
                      <Tag tone={rec.recommendation === '持有' ? 'warn' : 'up'}>{rec.recommendation}</Tag>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="px-3 py-6 text-center text-xs text-slate-500">
            本期晨报未产出推荐标的。
          </div>
        )}
      </Panel>

      {/* 风险提示 */}
      {report.risk_warnings.length > 0 && (
        <Panel className="border-warn/30 bg-warn/5">
          <SectionTitle>
            <span className="inline-flex items-center gap-1.5 text-warn">
              <AlertTriangle className="h-3 w-3" /> 风险提示
            </span>
          </SectionTitle>
          <ul className="space-y-1.5">
            {report.risk_warnings.map((warning, idx) => (
              <li key={idx} className="flex items-start gap-2 text-xs text-slate-300">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-warn" />
                {warning}
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <div className="py-2 text-center text-[10px] text-slate-600">
        本报告由量化系统自动生成，仅供参考，不构成投资建议
      </div>
    </div>
  );
}
