import { marketDate } from '../api/marketDate';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ResearchTasks } from '../components/ResearchTasks';
import { VirtualTrading } from '../components/VirtualTrading';
import { Header } from '../components/Header';
import { ResultContext } from '../components/ResultContext';
import { useJobResume } from '../hooks/useJobResume';
import { useBacktest } from '../hooks/useBacktest';
import { BacktestConsole } from '../components/BacktestConsole';
import type { BacktestConfig, BacktestResult } from '../types';
import { apiGet, apiPost } from '../api/client';
vi.mock('../api/client', () => ({ API_BASE: '', apiGet: vi.fn(), apiPost: vi.fn(), getApiErrorMessage: (e: Error) => e.message, isRequestCanceled: () => false }));
vi.mock('../hooks/useStrategyCatalog', () => ({ useStrategyCatalog: () => ({ byId: new Map(), strategies: [], loading: false, error: null }) }));

const config: BacktestConfig = { start_date: '2024-01-01', end_date: '2024-12-31', initial_capital: 1000000, factor: 'turtle', commission_rate: .0003, slippage_rate: .0003, pool: 'core', max_positions: 5, weight_mode: 'equal', stop_loss: -.08 };
const result: BacktestResult = { total_return: 0, history: [], trades: [], summary: { initial_capital: 1000000, final_value: 1000000, max_drawdown: 0, sharpe_ratio: 0 } };
beforeEach(() => { vi.resetAllMocks(); });

describe('reliable research UI', () => {
  it('uses Shanghai market dates across the UTC midnight boundary', () => {
    expect(marketDate(new Date('2026-10-10T17:00:00Z'))).toBe('2026-10-11');
  });
  it('groups navigation and preserves a direct page link', () => {
    const navigate = vi.fn(); render(<Header view="tasks" setView={navigate}/>);
    const link = screen.getByRole('link', { name: '数据与任务' });
    expect(link.getAttribute('href')).toBe('#tasks'); fireEvent.click(link); expect(navigate).toHaveBeenCalledWith('tasks');
  });
  it('submits all user parameters without hidden defaults', async () => {
    vi.mocked(apiPost).mockResolvedValue({ job_id: 'new-job' });
    vi.mocked(apiGet).mockImplementation(async path => String(path).endsWith('/result') ? result : { status: 'succeeded', kind: 'backtest' });
    function Harness() { const hook = useBacktest(); return <button onClick={() => void hook.runBacktest(config)}>执行测试回测</button>; }
    render(<Harness/>); fireEvent.click(screen.getByRole('button', {name:'执行测试回测'}));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/api/backtest/jobs', config, expect.any(Object)));
    expect(localStorage.getItem('momo:backtest:job')).toBe('new-job');
  });
  it('recovers a completed job from the URL after refresh', async () => {
    location.hash = '#console?job=saved';
    vi.mocked(apiGet).mockImplementation(async path => String(path).endsWith('/result') ? result : { status: 'succeeded', kind: 'backtest' });
    const value = vi.fn(), error = vi.fn(), loading = vi.fn();
    function Harness() { useJobResume('backtest', value, error, loading); return null; }
    render(<Harness/>); await waitFor(() => expect(value).toHaveBeenCalledWith(result));
    expect(apiPost).not.toHaveBeenCalled(); expect(loading).toHaveBeenLastCalledWith(false);
  });
  it('shows a failed fetch and retries task loading', async () => {
    let attempts = 0;
    vi.mocked(apiGet).mockImplementation(async path => { if (path === '/api/research/jobs') { if (attempts++ === 0) throw new Error('任务连接失败'); return []; } return { groups: {}, target_date: null }; });
    render(<ResearchTasks/>); await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('任务连接失败'));
    fireEvent.click(screen.getByRole('button', {name:'刷新任务 / 重试'}));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });
  it('displays stale market dates and missing symbols', async () => {
    vi.mocked(apiGet).mockImplementation(async path => path === '/api/research/jobs' ? [] : { target_date: '2026-10-09', note: '抽样', groups: { a_share: { total_local: 5000, checked_count: 30, fresh_count: 0, sample_latest_date: '2026-08-06', stale_symbols_sample: ['600000'] } } });
    render(<ResearchTasks/>); await waitFor(() => expect(screen.getByText(/2026-08-06/).textContent).toContain('2026-08-06'));
    expect(screen.getByText(/过期或缺失/).textContent).toContain('600000');
  });
  it('shows the actual data provenance and execution caveats', () => {
    render(<ResultContext result={{ ...result, engine_version:'daily-v2', data_as_of:'2024-12-31', quality_notes:['近似研究结果'] }}/>);
    expect(screen.getByText('行情截至 2024-12-31')).toBeTruthy(); expect(screen.getByText('近似研究结果')).toBeTruthy();
  });
  it('switches between preserved legacy accounts and v2 accounts', async () => {
    vi.mocked(apiGet).mockImplementation(async path => String(path).includes('/automation/') ? {} : []);
    render(<VirtualTrading/>);
    const select = await screen.findByRole('combobox', {name:'账户口径'});
    fireEvent.change(select, {target:{value:'legacy'}});
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/api/virtual-trade/accounts?version=legacy', expect.any(Object)));
    expect(localStorage.getItem('momo:account-version')).toBe('legacy');
  });
  it('changes the explicit approximate-execution configuration', () => {
    const update=vi.fn(); render(<BacktestConsole config={config} setConfig={update} onRun={vi.fn()} onSwitchStrategy={vi.fn()} loading={false}/>);
    fireEvent.click(screen.getByLabelText(/允许复权价近似研究/));
    expect(update).toHaveBeenCalledWith({...config, price_mode:'approximate_adjusted'});
  });
});
