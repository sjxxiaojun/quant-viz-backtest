import React, { useState, useEffect } from 'react';
import { 
  Zap, 
  Search, 
  ShieldAlert, 
  TrendingUp, 
  TrendingDown, 
  Calendar,
  AlertTriangle,
  RotateCcw,
  Sliders,
  DollarSign,
  PieChart as PieIcon,
  CheckCircle,
  HelpCircle,
  XCircle,
  Flame,
  Activity
} from 'lucide-react';
import { EChart } from './EChart';

interface PickItem {
  symkey: string;
  name: string;
  score: number;
  buy_price: number;
  trigger_low: number;
  trigger_high: number;
  stop_loss: number;
  take_profit: number;
  position: string;
  plan: string;
}

interface AvoidBuyItem {
  symkey: string;
  name: string;
  reason: string;
}

interface DayData {
  picks: PickItem[];
  avoid_buys: AvoidBuyItem[];
  win_rate?: number;
  verified_on?: string;
}

interface EngineParams {
  min_turnover: number;
  max_dist_ma10: number;
  max_amplitude: number;
  min_drop_5d: number;
}

export function OvernightConsole() {
  const [history, setHistory] = useState<Record<string, DayData>>({});
  const [params, setParams] = useState<EngineParams>({
    min_turnover: 300000000,
    max_dist_ma10: 0.12,
    max_amplitude: 0.15,
    min_drop_5d: -0.15
  });
  
  const [selectedDate, setSelectedDate] = useState<string>('');
  const [targetDateInput, setTargetDateInput] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch initial history
  const loadHistory = async () => {
    try {
      setLoading(true);
      const res = await fetch('/api/overnight/history');
      if (!res.ok) throw new Error('无法拉取历史记录数据');
      const data = await res.json();
      
      setHistory(data.history || {});
      if (data.params) setParams(data.params);
      
      // Default to the latest date in history
      const dates = Object.keys(data.history || {}).sort();
      if (dates.length > 0) {
        const latest = dates[dates.length - 1];
        setSelectedDate(latest);
        setTargetDateInput(latest);
      } else {
        // Fallback to today
        const todayStr = new Date().toISOString().slice(0, 10);
        setSelectedDate(todayStr);
        setTargetDateInput(todayStr);
      }
      setError(null);
    } catch (err: any) {
      setError(err.message || '初始化数据失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHistory();
  }, []);

  const handleScan = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetDateInput) return;
    
    try {
      setLoading(true);
      setError(null);
      
      const res = await fetch(`/api/overnight/scan?date=${targetDateInput}`, {
        method: 'POST'
      });
      
      if (!res.ok) {
        const errDetail = await res.json();
        throw new Error(errDetail.detail || '执行扫描引擎出错');
      }
      
      const result = await res.json();
      
      // Reload history and set selected date
      await loadHistory();
      if (result.date) {
        setSelectedDate(result.date);
        setTargetDateInput(result.date);
      }
    } catch (err: any) {
      setError(err.message || '运行扫描出错');
    } finally {
      setLoading(false);
    }
  };

  const getSortedDates = () => {
    return Object.keys(history).sort();
  };

  const getWinRateOption = () => {
    const dates = getSortedDates();
    const winRates = dates.map(d => history[d].win_rate !== undefined ? history[d].win_rate! * 100 : null);
    
    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        formatter: '{b} 胜率: {c}%',
        backgroundColor: '#111b2d',
        borderColor: '#1e293b',
        textStyle: { color: '#f8fafc', fontSize: 12 }
      },
      grid: {
        top: '15%',
        left: '5%',
        right: '5%',
        bottom: '10%',
        containLabel: true
      },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
        axisLabel: { color: '#94a3b8', fontSize: 10 }
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 100,
        axisLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.1)' } },
        splitLine: { lineStyle: { color: 'rgba(255, 255, 255, 0.05)' } },
        axisLabel: { formatter: '{value}%', color: '#94a3b8', fontSize: 10 }
      },
      series: [
        {
          name: '次日冲高胜率 (>2% 空间)',
          type: 'line',
          data: winRates,
          smooth: true,
          showAllSymbol: true,
          symbolSize: 8,
          lineStyle: {
            color: '#f59e0b',
            width: 3,
            shadowColor: 'rgba(245, 158, 11, 0.3)',
            shadowBlur: 10
          },
          itemStyle: {
            color: '#f59e0b',
            borderWidth: 2,
            borderColor: '#0f172a'
          },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(245, 158, 11, 0.2)' },
                { offset: 1, color: 'rgba(245, 158, 11, 0.0)' }
              ]
            }
          }
        }
      ]
    };
  };

  const selectedData = history[selectedDate];
  const sortedDates = getSortedDates();
  
  // Calculate average win rate
  const rates = sortedDates.map(d => history[d].win_rate).filter((r): r is number => r !== undefined);
  const avgWinRate = rates.length > 0 ? (rates.reduce((a, b) => a + b, 0) / rates.length * 100).toFixed(1) : 'N/A';

  // Determine current mode based on the last recorded win rate
  const getLastWinRate = () => {
    if (rates.length === 0) return null;
    return rates[rates.length - 1];
  };
  const lastWinRateVal = getLastWinRate();
  const adaptiveMode = lastWinRateVal === null 
    ? { name: '稳健模式', color: 'text-amber-400 border-amber-500/30 bg-amber-500/10' }
    : lastWinRateVal < 0.5 
      ? { name: '防守收紧模式', color: 'text-rose-400 border-rose-500/30 bg-rose-500/10', desc: '前日胜率偏低，引擎自动收紧选股偏离度与振幅，进入防御状态' }
      : lastWinRateVal >= 0.7
        ? { name: '进攻放宽模式', color: 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10', desc: '前日胜率表现强劲，引擎适当放宽偏离限制以捕捉更多黑马' }
        : { name: '常规修复模式', color: 'text-blue-400 border-blue-500/30 bg-blue-500/10', desc: '胜率平稳，保持默认均线回归与动量筛选参数' };

  return (
    <div className="space-y-8 animate-in fade-in duration-500 relative">
      {/* Background decoration */}
      <div className="absolute top-0 right-0 w-80 h-80 bg-amber-500/10 rounded-full blur-3xl -z-10 pointer-events-none" />
      <div className="absolute bottom-0 left-0 w-80 h-80 bg-blue-500/10 rounded-full blur-3xl -z-10 pointer-events-none" />

      {/* Main Glass Header Card */}
      <div className="relative p-8 rounded-3xl backdrop-blur-2xl border border-white/10 shadow-2xl flex flex-col lg:flex-row justify-between items-start lg:items-center gap-6 overflow-hidden" style={{ background: 'rgba(15, 23, 42, 0.4)' }}>
        <div className="space-y-2 relative z-10">
          <div className="flex items-center gap-2 text-amber-400 font-black tracking-widest text-xs uppercase bg-amber-500/10 px-3 py-1 rounded-full border border-amber-500/20 w-fit">
            <Flame className="w-3.5 h-3.5 animate-pulse" /> 尾盘短线回归策略
          </div>
          <h2 className="text-3xl font-extrabold tracking-tight text-white flex items-center gap-2">
            隔夜持股自适应工作站
          </h2>
          <p className="text-sm text-slate-400 max-w-2xl">
            每日 14:30 扫描全市场均线修复标的。内置胜率自适应反馈环：当前一天胜率偏低时自动收紧过滤阈值，胜率走高时自动切换为进攻参数。
          </p>
        </div>

        {/* Global Stats */}
        <div className="flex gap-4 w-full lg:w-auto relative z-10">
          <div className="flex-1 lg:flex-initial bg-slate-900/60 border border-white/5 rounded-2xl p-4 min-w-[130px]">
            <div className="text-xs text-slate-500 font-semibold mb-1">测试周期</div>
            <div className="text-xl font-bold text-slate-200">{sortedDates.length} 个交易日</div>
          </div>
          <div className="flex-1 lg:flex-initial bg-slate-900/60 border border-white/5 rounded-2xl p-4 min-w-[130px]">
            <div className="text-xs text-slate-500 font-semibold mb-1">多日平均胜率</div>
            <div className="text-xl font-extrabold text-amber-400">{avgWinRate}%</div>
          </div>
        </div>
      </div>

      {/* Interactive Control & Chart Panel */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        {/* Left Control Panel */}
        <div className="lg:col-span-4 space-y-6">
          
          {/* Action Trigger Card */}
          <div className="rounded-3xl p-6 backdrop-blur-xl border border-white/10 shadow-xl space-y-4" style={{ background: 'rgba(15, 23, 42, 0.4)' }}>
            <h3 className="text-base font-bold text-slate-200 flex items-center gap-2 border-b border-white/5 pb-3">
              <Calendar className="w-4 h-4 text-amber-500" /> 引擎扫描控制台
            </h3>
            
            <form onSubmit={handleScan} className="space-y-4">
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-400">运行基准日期</label>
                <div className="relative">
                  <input
                    type="date"
                    value={targetDateInput}
                    onChange={(e) => setTargetDateInput(e.target.value)}
                    className="w-full bg-slate-950/80 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-amber-500/50 transition-colors"
                  />
                </div>
              </div>
              
              <button
                type="submit"
                disabled={loading}
                className="w-full bg-gradient-to-r from-amber-600 to-amber-500 hover:from-amber-500 hover:to-amber-400 text-slate-950 font-bold py-3 px-4 rounded-xl text-xs uppercase tracking-wider flex items-center justify-center gap-2 shadow-lg shadow-amber-900/20 disabled:opacity-50 disabled:pointer-events-none transition-all duration-300"
              >
                {loading ? (
                  <>
                    <Activity className="w-4 h-4 animate-spin text-slate-950" />
                    正在扫描分析中...
                  </>
                ) : (
                  <>
                    <Zap className="w-4 h-4 fill-slate-950" />
                    执行尾盘扫描策略
                  </>
                )}
              </button>
            </form>

            {/* Error alerts */}
            {error && (
              <div className="rounded-xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-xs font-semibold text-rose-300">
                {error}
              </div>
            )}

            {/* Mode Indicator */}
            <div className={`rounded-2xl border p-4 space-y-2 ${adaptiveMode.color}`}>
              <div className="flex items-center gap-2 font-bold text-xs uppercase tracking-wider">
                <Sliders className="w-3.5 h-3.5" />
                自适应模式：{adaptiveMode.name}
              </div>
              {adaptiveMode.desc && (
                <p className="text-xs text-slate-400 leading-relaxed font-medium">
                  {adaptiveMode.desc}
                </p>
              )}
            </div>
          </div>

          {/* Engine Parameters */}
          <div className="rounded-3xl p-6 backdrop-blur-xl border border-white/10 shadow-xl space-y-4" style={{ background: 'rgba(15, 23, 42, 0.4)' }}>
            <h3 className="text-base font-bold text-slate-200 flex items-center gap-2 border-b border-white/5 pb-3">
              <Sliders className="w-4 h-4 text-cyan-500" /> 当前自适应参数状态
            </h3>
            
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-slate-950/40 p-3 rounded-xl border border-white/5">
                <div className="text-[10px] text-slate-500 font-bold mb-1">最小成交额</div>
                <div className="text-sm font-semibold text-slate-300">{(params.min_turnover / 100000000).toFixed(1)} 亿</div>
              </div>
              <div className="bg-slate-950/40 p-3 rounded-xl border border-white/5">
                <div className="text-[10px] text-slate-500 font-bold mb-1">MA10最大偏离</div>
                <div className="text-sm font-semibold text-slate-300">{(params.max_dist_ma10 * 100).toFixed(1)}%</div>
              </div>
              <div className="bg-slate-950/40 p-3 rounded-xl border border-white/5">
                <div className="text-[10px] text-slate-500 font-bold mb-1">最大振幅阀值</div>
                <div className="text-sm font-semibold text-slate-300">{(params.max_amplitude * 100).toFixed(1)}%</div>
              </div>
              <div className="bg-slate-950/40 p-3 rounded-xl border border-white/5">
                <div className="text-[10px] text-slate-500 font-bold mb-1">5日跌幅下限</div>
                <div className="text-sm font-semibold text-slate-300">{(params.min_drop_5d * 100).toFixed(1)}%</div>
              </div>
            </div>
          </div>
        </div>

        {/* Right Chart Area */}
        <div className="lg:col-span-8">
          <div className="rounded-3xl p-6 backdrop-blur-xl border border-white/10 shadow-xl space-y-4 h-full flex flex-col justify-between" style={{ background: 'rgba(15, 23, 42, 0.4)' }}>
            <div className="flex justify-between items-center border-b border-white/5 pb-3">
              <h3 className="text-base font-bold text-slate-200 flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-emerald-500" /> 回测胜率跟踪曲线 (次日 &gt;2% 溢价)
              </h3>
              
              {/* Date selection dropdown */}
              <select
                value={selectedDate}
                onChange={(e) => {
                  setSelectedDate(e.target.value);
                  setTargetDateInput(e.target.value);
                }}
                className="bg-slate-950 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-slate-300 font-medium focus:outline-none"
              >
                {sortedDates.map(d => (
                  <option key={d} value={d}>
                    {d} (胜率: {history[d].win_rate !== undefined ? `${(history[d].win_rate! * 100).toFixed(0)}%` : '待测'})
                  </option>
                ))}
              </select>
            </div>
            
            {sortedDates.length > 0 ? (
              <EChart option={getWinRateOption()} className="w-full h-[230px]" />
            ) : (
              <div className="min-h-[230px] flex items-center justify-center text-slate-500 text-xs font-semibold">
                无历史扫描数据，请先运行一次尾盘扫描。
              </div>
            )}
            
            <div className="text-[10px] text-slate-500 font-medium italic">
              * 提示：可以在折线图下方的下拉菜单中切换历史日期，以查阅任意历史日期的最终选股推荐及避雷名单。
            </div>
          </div>
        </div>
      </div>

      {/* Results Section */}
      {selectedData ? (
        <div className="space-y-8">
          
          {/* Picks & Trade Plans */}
          <div className="rounded-3xl p-6 backdrop-blur-xl border border-white/10 shadow-xl space-y-6" style={{ background: 'rgba(15, 23, 42, 0.4)' }}>
            <div className="flex justify-between items-center border-b border-white/5 pb-3">
              <h3 className="text-base font-bold text-slate-200 flex items-center gap-2">
                <Zap className="w-4 h-4 text-amber-500 fill-amber-500" />
                {selectedDate} 建议尾盘潜伏名单与交易计划表
              </h3>
              
              {selectedData.win_rate !== undefined && (
                <div className="flex items-center gap-2 text-xs font-bold text-emerald-400 bg-emerald-500/10 px-3 py-1 rounded-full border border-emerald-500/20">
                  <CheckCircle className="w-3.5 h-3.5" /> 次日实际验证胜率：{(selectedData.win_rate * 100).toFixed(0)}%
                </div>
              )}
            </div>
            
            {selectedData.picks && selectedData.picks.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {selectedData.picks.map((pick, idx) => (
                  <div key={pick.symkey} className="bg-slate-950/60 border border-white/5 hover:border-amber-500/30 rounded-2xl p-5 space-y-4 transition-all duration-300 group hover:shadow-lg hover:shadow-amber-500/5 relative overflow-hidden">
                    
                    {/* Corner rank number */}
                    <div className="absolute top-0 right-0 w-8 h-8 bg-slate-900 border-l border-b border-white/5 rounded-bl-xl text-xs font-bold text-slate-600 flex items-center justify-center group-hover:text-amber-500 group-hover:bg-amber-500/10 transition-colors">
                      {idx + 1}
                    </div>

                    <div className="space-y-1">
                      <h4 className="text-base font-bold text-slate-100 group-hover:text-amber-400 transition-colors">{pick.name}</h4>
                      <p className="text-[10px] text-slate-500 font-bold tracking-wider">{pick.symkey}</p>
                    </div>

                    <div className="grid grid-cols-2 gap-4 text-xs">
                      <div className="bg-slate-900/60 p-2 rounded-xl">
                        <span className="text-[10px] text-slate-500 font-bold block">信号/买入价</span>
                        <span className="font-extrabold text-slate-200">{pick.buy_price.toFixed(2)}</span>
                      </div>
                      <div className="bg-slate-900/60 p-2 rounded-xl">
                        <span className="text-[10px] text-slate-500 font-bold block">建议仓位</span>
                        <span className="font-extrabold text-slate-200">{pick.position || '8%'}</span>
                      </div>
                    </div>

                    <div className="bg-slate-900/40 border border-white/5 rounded-xl p-3 space-y-2 text-[11px]">
                      <div className="flex justify-between">
                        <span className="text-slate-500 font-semibold">触发区间:</span>
                        <span className="text-slate-300 font-extrabold">{pick.trigger_low.toFixed(2)} - {pick.trigger_high.toFixed(2)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-rose-500 font-semibold flex items-center gap-0.5">
                          <TrendingDown className="w-3 h-3" /> 止损价:
                        </span>
                        <span className="text-rose-300 font-extrabold">{pick.stop_loss.toFixed(2)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-emerald-500 font-semibold flex items-center gap-0.5">
                          <TrendingUp className="w-3 h-3" /> 第一止盈价:
                        </span>
                        <span className="text-emerald-300 font-extrabold">{pick.take_profit.toFixed(2)}</span>
                      </div>
                    </div>

                    <div className="text-[11px] text-slate-400 leading-relaxed bg-amber-500/5 border border-amber-500/10 rounded-xl p-3 font-medium">
                      <span className="font-bold text-amber-500 block mb-0.5">操盘计划：</span>
                      {pick.plan}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-2xl border border-dashed border-white/10 p-8 text-center text-slate-500 font-bold text-sm">
                ⚠️ 本日引擎未扫出满足严苛均线形态的标的，触发策略空仓防守机制，建议持币观望。
              </div>
            )}
          </div>

          {/* Avoid buys (Red/Warning Banner) */}
          <div className="rounded-3xl p-6 backdrop-blur-xl border border-rose-500/10 shadow-xl space-y-4" style={{ background: 'rgba(29, 13, 20, 0.4)' }}>
            <h3 className="text-base font-bold text-rose-200 flex items-center gap-2 border-b border-rose-500/10 pb-3">
              <ShieldAlert className="w-4 h-4 text-rose-500" />
              【容易误买但今日不建议抄底】警示名单
            </h3>
            
            {selectedData.avoid_buys && selectedData.avoid_buys.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {selectedData.avoid_buys.map(avoid => (
                  <div key={avoid.symkey} className="bg-slate-950/40 border border-rose-500/10 rounded-2xl p-4 space-y-2">
                    <div className="flex justify-between items-start">
                      <div className="space-y-0.5">
                        <span className="text-sm font-bold text-rose-300">{avoid.name}</span>
                        <span className="text-[9px] text-slate-600 block font-bold tracking-wider">{avoid.symkey}</span>
                      </div>
                      <div className="bg-rose-500/10 text-rose-400 border border-rose-500/20 px-2 py-0.5 rounded text-[9px] font-extrabold uppercase">
                        风险过滤
                      </div>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-relaxed font-semibold">
                      {avoid.reason}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-xs text-slate-500 font-medium italic">
                没有符合风险预警的排除标的。
              </div>
            )}
          </div>

        </div>
      ) : null}
    </div>
  );
}
