/**
 * D-16: 策略置信度、回测边界与量化合规披露页 (Disclosure)
 */

import React from 'react';
import { ShieldAlert, AlertTriangle, CheckCircle2, Info } from 'lucide-react';
import { Panel, SectionTitle, Tag } from '../components/ui';

export function DisclosurePage() {
  return (
    <div className="space-y-6 max-w-4xl mx-auto pb-12">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center">
          <ShieldAlert className="w-6 h-6 text-amber-400" />
        </div>
        <div>
          <h2 className="text-2xl font-bold text-slate-100">策略置信度与量化模型合规披露</h2>
          <p className="text-xs text-slate-400">遵循量化金融铁律与严谨科研准则，如实披露全部模型假设与样本边界</p>
        </div>
      </div>

      {/* 1. 低统计置信度策略披露 */}
      <Panel level={1}>
        <SectionTitle right={<Tag tone="warn">低样本量警戒</Tag>}>
          1. 低统计置信度策略披露 (Low Sample Size Caveat)
        </SectionTitle>
        <div className="mt-4 space-y-3 text-xs text-slate-300 leading-relaxed">
          <p>
            <strong className="text-amber-400">【涨停后十字星 (limit_up_doji)】</strong>
            在 2022–2024 年全市场样本池 10,890 条 Bar 数据中，严格符合“昨日涨停 + 今日缩量收十字星”形态的有效触发仅 <span className="font-mono text-amber-300 font-bold">6 次</span>。
          </p>
          <div className="p-3 bg-slate-900/60 rounded-ctl border border-line space-y-1.5 font-mono text-[11px] text-slate-400">
            <div>• 统计有效性评级：LOW (低于大数定律 N≥30 最小置信区间)</div>
            <div>• 实盘部署建议：仅供形态工程化和事件驱动框架示例，严禁单策略重仓实盘</div>
            <div>• 前端展示策略：已从推荐榜单中降权，并在策略卡片上常态化打标【低置信度/示例策略】</div>
          </div>
        </div>
      </Panel>

      {/* 2. 市场状态与空仓机制披露 */}
      <Panel level={1}>
        <SectionTitle right={<Tag tone="ok">物理不变量修复</Tag>}>
          2. 市场状态切换与空仓真实性披露 (Bear Regime Truthfulness)
        </SectionTitle>
        <div className="mt-4 space-y-3 text-xs text-slate-300 leading-relaxed">
          <p>
            <strong className="text-blue-400">【自适应双模与多因子策略 (ai_adaptive_pro / regime_adaptive)】</strong>
            已全面根除历史“熊市不空仓 Bug”。在识别为下行熊市行情时，系统 100% 强制清空持仓并转为现金管理模式，绝不在下行周期逆势建仓。
          </p>
          <div className="p-3 bg-slate-900/60 rounded-ctl border border-line space-y-1.5 font-mono text-[11px] text-slate-400">
            <div>• 曲线诚实性：修复后在 2022-2024 单边下行期收益曲线表现平稳，废除任何历史虚高数据</div>
            <div>• 口径唯一化：以最新无偏回测内核输出结果为平台唯一口径</div>
          </div>
        </div>
      </Panel>

      {/* 3. A股交易制度与成本模型约束 */}
      <Panel level={1}>
        <SectionTitle right={<Tag tone="accent">A股微观结构</Tag>}>
          3. 撮合内核与 A 股交易纪律约束 (Microstructure Rules)
        </SectionTitle>
        <div className="mt-4 space-y-3 text-xs text-slate-300 leading-relaxed">
          <ul className="list-disc list-inside space-y-2 text-slate-300">
            <li>
              <strong className="text-slate-100">T+1 物理 Lot 隔离</strong>：当日新开仓 Lot 在当日卖出撮合与风险退出逻辑中物理不可达，杜绝任何违规日内回转。
            </li>
            <li>
              <strong className="text-slate-100">DEFERRED_INTENT 延迟止损</strong>：当日新仓触发止损时仅记录意图，平仓执行严格由 T+1 日开盘实际市场价格决定，消灭偷看 D 日日内最低价的前视偏差。
            </li>
            <li>
              <strong className="text-slate-100">ETF 免征印花税</strong>：ETF/LOF/可转债代码卖出印花税严格按 0.00% 结算，A股个股卖出按 0.05% 法定标准计征。
            </li>
            <li>
              <strong className="text-slate-100">滑点分层透传</strong>：日内执行采用 0.03% 机构级滑点，收盘价调仓采用 0.15% 独立收盘滑点。
            </li>
          </ul>
        </div>
      </Panel>
    </div>
  );
}
