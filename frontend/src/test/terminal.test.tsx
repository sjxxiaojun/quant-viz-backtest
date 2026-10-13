import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { apiGet, apiPost } from '../api/client';
import { ResearchAssistant } from '../components/research/ResearchAssistant';
import { ComparisonPanel } from '../components/research/ComparisonPanel';
import { ExperimentWorkbench } from '../components/research/ExperimentWorkbench';
import { ConfigPanel } from '../components/factor-lab/ConfigPanel';
import type { BacktestConfig, BacktestResult } from '../types';
import { restoreBacktestConfig } from '../api/backtestConfig';
vi.mock('../api/client', () => ({
  API_BASE: '',
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  getApiErrorMessage: (e: Error) => e.message,
}));
vi.mock('../components/EChart', () => ({
  EChart: () => <div aria-label="比较图表" />,
}));
vi.mock('../hooks/useStrategyCatalog', () => ({
  useStrategyCatalog: () => ({
    catalog: [{ id: 'turtle', name: '海龟策略' }],
    byId: new Map(),
  }),
}));
const base: BacktestConfig = {
  start_date: '2023-01-01',
  end_date: '2024-12-31',
  initial_capital: 1000000,
  factor: 'turtle',
  pool: 'custom',
  stocks: ['000001'],
  commission_rate: 0.0003,
  slippage_rate: 0.0003,
  max_positions: 5,
  weight_mode: 'equal',
  stop_loss: -0.08,
};
const result: BacktestResult = {
  total_return: 0.1,
  history: [],
  trades: [],
  summary: {
    initial_capital: 1000000,
    final_value: 1100000,
    max_drawdown: -0.2,
    sharpe_ratio: 0.5,
  },
};
beforeEach(() => {
  vi.resetAllMocks();
  location.hash = '';
});
describe('terminal research workflows', () => {
  it('restores actual saved parameters including explicit zero costs and price mode', () => {
    const restored = restoreBacktestConfig({...base, commission_rate:0, close_slippage_rate:0, price_mode:'approximate_adjusted',stocks:null});
    expect(restored?.factor).toBe('turtle');
    expect(restored?.commission_rate).toBe(0);
    expect(restored?.close_slippage_rate).toBe(0);
    expect(restored?.price_mode).toBe('approximate_adjusted');
    expect(restored?.stocks).toBeUndefined();
  });
  it('uses local analysis by default and does not submit an experiment', async () => {
    vi.mocked(apiPost).mockResolvedValue({
      source: 'local',
      job_ids: ['saved'],
      summary: '本地报告',
      observations: [],
      proposals: [],
    });
    const submit = vi.fn();
    render(
      <ResearchAssistant
        selected={['saved']}
        requests={{ saved: base }}
        onSubmit={submit}
      />,
    );
    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(
      false,
    );
    fireEvent.click(screen.getByRole('button', { name: '分析所选结果' }));
    await screen.findByText('本地报告');
    expect(apiPost).toHaveBeenCalledWith('/api/research/analysis', {
      job_ids: ['saved'],
      use_external: false,
    });
    expect(submit).not.toHaveBeenCalled();
  });
  it('shows proposed parameters and only submits after a click', async () => {
    const proposal = {
      job_id: 'saved',
      changes: { stop_loss: -0.05 },
      reason: '比较更紧的止损',
    };
    vi.mocked(apiPost).mockResolvedValue({
      source: 'external',
      job_ids: ['saved'],
      summary: '基于任务 saved',
      observations: [],
      proposals: [proposal],
    });
    const submit = vi.fn().mockResolvedValue(undefined);
    render(
      <ResearchAssistant
        selected={['saved']}
        requests={{ saved: base }}
        onSubmit={submit}
      />,
    );
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: '分析所选结果' }));
    await screen.findByText(/stop_loss: -0.05/);
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '确认参数并提交实验' }));
    await waitFor(() => expect(submit).toHaveBeenCalledWith(proposal));
    await screen.findByText('已提交实验');
  });
  it('does not display a missing benchmark as zero excess return', () => {
    render(<ComparisonPanel entries={[{ label: '实验A', result }]} />);
    const row = screen.getByText('实验A').closest('tr')!;
    expect(row.children[1].textContent).toBe('10.00%');
    expect(row.children[2].textContent).toBe('—');
    expect(row.children[3].textContent).toBe('—');
    fireEvent.click(screen.getByRole('button', { name: '回撤曲线' }));
    expect(screen.getByLabelText('比较图表')).toBeTruthy();
  });
  it('restores a saved parameter experiment without resubmitting it', async () => {
    location.hash = '#experiment?job=saved';
    const experiment = {
      winner_candidate_id: 0,
      test_result: result,
      split: {
        validation_start: '2024-01-01',
        validation_end: '2024-06-30',
        test_start: '2024-07-01',
        test_end: '2024-12-31',
      },
      validation_candidates: [
        {
          candidate_id: 0,
          changes: { stop_loss: -0.05 },
          metrics: { net_return: 0.1, max_drawdown: -0.2 },
        },
      ],
    };
    vi.mocked(apiGet).mockImplementation(async (path) =>
      String(path).endsWith('/result')
        ? experiment
        : {
            kind: 'experiment',
            status: 'succeeded',
            stage: '完成',
            request: { base, candidates: [{ stop_loss: -0.05 }] },
          },
    );
    render(<ExperimentWorkbench config={base} />);
    await screen.findByText('验证期排名');
    expect(apiPost).not.toHaveBeenCalled();
    expect((screen.getByLabelText('候选1止损') as HTMLInputElement).value).toBe(
      '-5',
    );
  });
  it('limits the editable candidate list to twelve', () => {
    render(<ExperimentWorkbench config={base} />);
    const add = screen.getByRole('button', { name: '添加候选（最多12组）' });
    for (let i = 0; i < 9; i++) fireEvent.click(add);
    expect((add as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getAllByRole('button', { name: '移除' })).toHaveLength(12);
  });
  it('keeps the new model opt-in separate from approximate-price research', () => {
    const change = vi.fn();
    render(
      <ConfigPanel
        config={{
          start_date: base.start_date,
          end_date: base.end_date,
          pool: 'core',
          label: 'next_5d_ret',
          top_n: 5,
        }}
        onChange={change}
        dateRangeInvalid={false}
      />,
    );
    fireEvent.click(screen.getByLabelText(/加入 HistGradientBoosting/));
    expect(change).toHaveBeenCalledWith({
      enable_hist_gradient_boosting: true,
    });
  });
});
