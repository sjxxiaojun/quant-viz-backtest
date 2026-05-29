import React, { useState, useEffect } from 'react';
import { Newspaper, RefreshCw, TrendingUp, TrendingDown, AlertTriangle, Star, Clock, BarChart3, Target, Shield } from 'lucide-react';
import { apiGet } from '../api/client';

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
}

export function DailyReport() {
  const [report, setReport] = useState<DailyReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const fetchReport = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiGet<DailyReportData>('/api/daily-report/latest');
      setReport(data);
    } catch (err: any) {
      setError(err.message || '获取晨报失败');
    } finally {
      setLoading(false);
    }
  };

  const generateReport = async () => {
    setGenerating(true);
    try {
      const response = await fetch('http://127.0.0.1:8080/api/daily-report/generate', {
        method: 'POST',
      });
      if (!response.ok) {
        throw new Error('生成失败');
      }
      await fetchReport();
    } catch (err: any) {
      setError(err.message || '生成晨报失败');
    } finally {
      setGenerating(false);
    }
  };

  useEffect(() => {
    fetchReport();
  }, []);

  if (loading) {
    return (
      <div className="min-h-[400px] flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-4 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin mx-auto" />
          <p className="text-slate-400 text-sm">正在加载晨报...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div className="rounded-2xl border border-rose-500/20 bg-rose-500/10 px-5 py-4 text-sm text-rose-100">
          {error}
        </div>
        <div className="flex gap-3">
          <button
            onClick={fetchReport}
            className="px-4 py-2 bg-blue-600 text-white rounded-xl text-sm font-bold hover:bg-blue-500 transition-colors"
          >
            重试
          </button>
          <button
            onClick={generateReport}
            disabled={generating}
            className="px-4 py-2 bg-emerald-600 text-white rounded-xl text-sm font-bold hover:bg-emerald-500 transition-colors disabled:opacity-50"
          >
            {generating ? '生成中...' : '生成新晨报'}
          </button>
        </div>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="space-y-6">
        <div className="rounded-2xl border border-slate-700/50 bg-slate-800/50 px-5 py-8 text-center">
          <Newspaper className="w-12 h-12 text-slate-500 mx-auto mb-4" />
          <p className="text-slate-400 mb-4">暂无晨报数据</p>
          <button
            onClick={generateReport}
            disabled={generating}
            className="px-6 py-3 bg-emerald-600 text-white rounded-xl text-sm font-bold hover:bg-emerald-500 transition-colors disabled:opacity-50"
          >
            {generating ? '生成中...' : '生成今日晨报'}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-in slide-in-from-bottom-4 duration-500">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-emerald-600 rounded-xl flex items-center justify-center shadow-lg shadow-emerald-900/20">
              <Newspaper className="text-white w-6 h-6" />
            </div>
            <h2 className="text-2xl font-black tracking-tighter text-emerald-500">
              量化晨报
            </h2>
          </div>
          <p className="text-slate-500 text-xs ml-13">
            {report.report_date} | 生成时间: {new Date(report.generated_at).toLocaleString('zh-CN')}
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={fetchReport}
            className="px-4 py-2 bg-slate-700/50 text-slate-300 rounded-xl text-sm font-bold hover:bg-slate-600/50 transition-colors flex items-center gap-2"
          >
            <RefreshCw className="w-4 h-4" /> 刷新
          </button>
          <button
            onClick={generateReport}
            disabled={generating}
            className="px-4 py-2 bg-emerald-600 text-white rounded-xl text-sm font-bold hover:bg-emerald-500 transition-colors disabled:opacity-50 flex items-center gap-2"
          >
            {generating ? <Clock className="w-4 h-4 animate-spin" /> : <Newspaper className="w-4 h-4" />}
            {generating ? '生成中...' : '生成新晨报'}
          </button>
        </div>
      </div>

      {/* Market Overview */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="rounded-2xl border border-slate-700/50 bg-slate-800/50 p-5">
          <div className="flex items-center gap-3 mb-3">
            <BarChart3 className="w-5 h-5 text-blue-400" />
            <span className="text-slate-400 text-xs font-bold uppercase tracking-wider">股票总数</span>
          </div>
          <p className="text-3xl font-black text-white">{report.market_overview.total_stocks}</p>
        </div>
        <div className="rounded-2xl border border-slate-700/50 bg-slate-800/50 p-5">
          <div className="flex items-center gap-3 mb-3">
            <Target className="w-5 h-5 text-emerald-400" />
            <span className="text-slate-400 text-xs font-bold uppercase tracking-wider">信号股票</span>
          </div>
          <p className="text-3xl font-black text-emerald-400">{report.market_overview.signal_count}</p>
        </div>
        <div className="rounded-2xl border border-slate-700/50 bg-slate-800/50 p-5">
          <div className="flex items-center gap-3 mb-3">
            <TrendingUp className="w-5 h-5 text-cyan-400" />
            <span className="text-slate-400 text-xs font-bold uppercase tracking-wider">平均分数</span>
          </div>
          <p className="text-3xl font-black text-cyan-400">{report.market_overview.avg_score.toFixed(4)}</p>
        </div>
        <div className="rounded-2xl border border-slate-700/50 bg-slate-800/50 p-5">
          <div className="flex items-center gap-3 mb-3">
            <Shield className="w-5 h-5 text-amber-400" />
            <span className="text-slate-400 text-xs font-bold uppercase tracking-wider">Test RankIC</span>
          </div>
          <p className="text-3xl font-black text-amber-400">{report.factor_status.test_rank_ic.toFixed(4)}</p>
        </div>
      </div>

      {/* Factor Status */}
      <div className="rounded-2xl border border-slate-700/50 bg-slate-800/50 p-6">
        <h3 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
          <Star className="w-5 h-5 text-amber-400" /> 因子状态
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <p className="text-slate-500 text-xs mb-1">最佳因子</p>
            <p className="text-white font-bold">{report.factor_status.best_factor}</p>
          </div>
          <div>
            <p className="text-slate-500 text-xs mb-1">Test Top20收益</p>
            <p className="text-emerald-400 font-bold">{(report.factor_status.test_top20_ret * 100).toFixed(2)}%</p>
          </div>
          <div>
            <p className="text-slate-500 text-xs mb-1">模型融合</p>
            <p className="text-white font-bold">
              {report.factor_status.model_recipe.baseline_model} {Math.round(report.factor_status.model_recipe.baseline_weight * 100)}% + {report.factor_status.model_recipe.nonlinear_model} {Math.round(report.factor_status.model_recipe.nonlinear_weight * 100)}%
            </p>
          </div>
        </div>
      </div>

      {/* Recommendations Table */}
      <div className="rounded-2xl border border-slate-700/50 bg-slate-800/50 overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-700/50">
          <h3 className="text-lg font-bold text-white flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-emerald-400" /> 今日Top 10推荐
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700/50">
                <th className="px-6 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">排名</th>
                <th className="px-6 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">代码</th>
                <th className="px-6 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">名称</th>
                <th className="px-6 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">最新价</th>
                <th className="px-6 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">涨跌幅</th>
                <th className="px-6 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">分数</th>
                <th className="px-6 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">信号</th>
                <th className="px-6 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">持仓</th>
                <th className="px-6 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">建议</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {report.recommendations.map((rec) => (
                <tr key={rec.rank} className="hover:bg-slate-700/30 transition-colors">
                  <td className="px-6 py-4">
                    <span className={`inline-flex items-center justify-center w-8 h-8 rounded-full text-xs font-bold ${
                      rec.rank <= 3 ? 'bg-emerald-500/20 text-emerald-400' : 'bg-slate-700/50 text-slate-400'
                    }`}>
                      {rec.rank}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm text-slate-300 font-mono">{rec.stock_code}</td>
                  <td className="px-6 py-4 text-sm text-white font-bold">{rec.stock_name}</td>
                  <td className="px-6 py-4">
                    {rec.current_price ? (
                      <span className="text-sm text-white font-mono">
                        ¥{rec.current_price.toFixed(2)}
                      </span>
                    ) : (
                      <span className="text-slate-500 text-xs">--</span>
                    )}
                  </td>
                  <td className="px-6 py-4">
                    {rec.pct_chg !== null && rec.pct_chg !== undefined ? (
                      <span className={`inline-flex items-center gap-1 text-sm font-bold ${
                        rec.pct_chg > 0 ? 'text-rose-400' : rec.pct_chg < 0 ? 'text-emerald-400' : 'text-slate-400'
                      }`}>
                        {rec.pct_chg > 0 ? <TrendingUp className="w-3 h-3" /> : rec.pct_chg < 0 ? <TrendingDown className="w-3 h-3" /> : null}
                        {rec.pct_chg > 0 ? '+' : ''}{rec.pct_chg.toFixed(2)}%
                      </span>
                    ) : (
                      <span className="text-slate-500 text-xs">--</span>
                    )}
                  </td>
                  <td className="px-6 py-4">
                    <span className={`text-sm font-bold ${
                      rec.score >= 0.9 ? 'text-emerald-400' : rec.score >= 0.7 ? 'text-cyan-400' : 'text-slate-400'
                    }`}>
                      {rec.score.toFixed(4)}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    {rec.signal === 1 ? (
                      <span className="inline-flex items-center gap-1 text-emerald-400 text-xs font-bold">
                        <TrendingUp className="w-3 h-3" /> 买入
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-slate-500 text-xs">
                        <TrendingDown className="w-3 h-3" /> 观察
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4">
                    {rec.held ? (
                      <span className="inline-flex items-center gap-1 text-amber-400 text-xs font-bold">
                        <Star className="w-3 h-3" /> {rec.holding_strategies.join(', ')}
                      </span>
                    ) : (
                      <span className="text-slate-500 text-xs">未持仓</span>
                    )}
                  </td>
                  <td className="px-6 py-4">
                    <span className={`inline-flex px-3 py-1 rounded-full text-xs font-bold ${
                      rec.recommendation === '持有' ? 'bg-amber-500/20 text-amber-400' : 'bg-emerald-500/20 text-emerald-400'
                    }`}>
                      {rec.recommendation}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Risk Warnings */}
      {report.risk_warnings.length > 0 && (
        <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 p-6">
          <h3 className="text-lg font-bold text-amber-400 mb-4 flex items-center gap-2">
            <AlertTriangle className="w-5 h-5" /> 风险提示
          </h3>
          <ul className="space-y-2">
            {report.risk_warnings.map((warning, idx) => (
              <li key={idx} className="text-amber-200/80 text-sm flex items-start gap-2">
                <span className="w-1.5 h-1.5 bg-amber-400 rounded-full mt-2 flex-shrink-0" />
                {warning}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Footer */}
      <div className="text-center text-slate-600 text-xs py-4">
        * 本报告由量化系统自动生成，仅供参考，不构成投资建议 *
      </div>
    </div>
  );
}
