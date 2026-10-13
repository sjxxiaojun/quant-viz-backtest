import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { pollJobResult } from '../api/pollJob';
import { apiGet, apiPost, getApiErrorMessage, getApiErrorPayload, isRequestCanceled } from '../api/client';
import { isRecord, toStr } from '../components/factor-lab/parse';
import {
  DEFAULT_FACTOR_LAB_RUN_CONFIG,
  normalizeBacktest,
  normalizeFactorLabResult,
  normalizeReadiness,
} from '../components/factor-lab/normalize';
import {
  normalizeSelfIteration,
  normalizeStrategyLifecycle,
  normalizeStressTest,
} from '../components/factor-lab/normalizeLifecycle';
import type {
  FactorLabFailureState,
  FactorLabHookState,
  FactorLabRunConfig,
  FactorLabRunReadiness,
} from '../types';

const PREVIOUS_REAL_RESULT_NOTICE = '当前展示的是上次真实结果';

/** readiness 检查防抖窗口: 日期逐字符输入/连续点选只发最后一次 */
const READINESS_DEBOUNCE_MS = 500;

function buildBacktestRequest(config: FactorLabRunConfig) {
  return {
    start_date: config.start_date,
    end_date: config.end_date,
    initial_capital: 1000000,
    factor: 'ml_factor_ranker',
    enable_hist_gradient_boosting: config.enable_hist_gradient_boosting ?? false,
    price_mode: config.price_mode ?? 'strict_raw',
    commission_rate: 0.0003,
    slippage_rate: 0.0003,
    pool: config.pool,
    max_positions: config.top_n,
    weight_mode: 'score',
    stop_loss: -0.08,
    label: config.label,
    top_n: config.top_n,
    max_symbols: config.max_symbols,
  };
}

function buildStressTestRequest(config: FactorLabRunConfig) {
  return {
    pool: config.pool,
    max_symbols: Math.max(3, Math.min(config.max_symbols ?? 300, 500)),
    top_n: config.top_n,
    initial_capital: 1000000,
    factors: ['ml_factor_ranker'],
    horizon_days: 260,
    paths_per_scenario: 2,
    seed: 42,
    scenarios: ['bull', 'bear', 'sideways'],
    anchor_date: config.end_date,
    lookback_days: 260,
    commission_rate: 0.0003,
    stamp_tax_rate: 0.001,
    slippage_rate: 0.0003,
    stop_loss: -0.08,
  };
}

function buildFailure(
  action: FactorLabFailureState['action'],
  error: unknown,
  config?: FactorLabRunConfig,
  fallbackDetail = 'Factor Lab 请求失败'
): FactorLabFailureState {
  const payload = getApiErrorPayload(error);
  if (payload) {
    const detail = isRecord(payload)
      ? toStr(payload.detail, getApiErrorMessage(error, fallbackDetail))
      : getApiErrorMessage(error, fallbackDetail);
    return {
      action,
      detail,
      error_code: isRecord(payload) ? toStr(payload.error_code) || null : null,
      config,
      run_readiness: isRecord(payload) ? normalizeReadiness(payload.run_readiness) : null,
    };
  }
  return {
    action,
    detail: error instanceof Error ? error.message || fallbackDetail : fallbackDetail,
    error_code: null,
    config,
    run_readiness: null,
  };
}

async function fetchReadiness(config: FactorLabRunConfig, signal?: AbortSignal): Promise<{
  readiness: FactorLabRunReadiness | null;
  failure: FactorLabFailureState | null;
}> {
  try {
    const response = await apiPost<unknown>('/api/factor-lab/readiness', config, { timeout: 20000, signal });
    const payload = isRecord(response) ? response.run_readiness ?? response : response;
    return { readiness: normalizeReadiness(payload), failure: null };
  } catch (error) {
    if (isRequestCanceled(error)) {
      return { readiness: null, failure: null };
    }
    const failure = buildFailure('checkReadiness', error, config, '运行前检查失败');
    return { readiness: failure.run_readiness ?? null, failure };
  }
}

export function useFactorLab(currentConfig?: FactorLabRunConfig) {
  const effectiveConfig = currentConfig ?? DEFAULT_FACTOR_LAB_RUN_CONFIG;
  const [state, setState] = useState<FactorLabHookState>({
    result: null,
    latestRealResult: null,
    readiness: null,
    checkingReadiness: false,
    loading: false,
    loadingAction: null,
    error: null,
    notice: null,
    lastFailure: null,
    versionActionLoading: null,
  });
  const requestSeq = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const updateState = useCallback((patch: Partial<FactorLabHookState>) => {
    setState((prev) => ({ ...prev, ...patch }));
  }, []);

  const beginRequest = useCallback(() => {
    const requestId = requestSeq.current + 1;
    requestSeq.current = requestId;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    return { requestId, signal: controller.signal };
  }, []);

  const isLatestRequest = useCallback((requestId: number) => requestSeq.current === requestId, []);

  const loadLatest = useCallback(async () => {
    const { requestId, signal } = beginRequest();
    updateState({ loading: true, loadingAction: 'load', error: null, notice: null, lastFailure: null });
    try {
      const query = location.hash.startsWith('#factorLab') ? location.hash.split('?')[1] : undefined;
      const job = new URLSearchParams(query).get('job');
      const response = job ? await pollJobResult<unknown>(`/api/research/jobs/${job}`, `/api/research/jobs/${job}/result`, { signal, timeoutMs: 60 * 60 * 1000 }) : await apiGet<unknown>('/api/factor-lab/results', { timeout: 20000, signal });
      if (!isLatestRequest(requestId)) return null;
      const normalized = normalizeFactorLabResult(response, DEFAULT_FACTOR_LAB_RUN_CONFIG);
      setState((prev) => ({
        ...prev,
        result: normalized,
        latestRealResult: normalized,
        readiness: normalized?.run_readiness ?? prev.readiness,
        loading: false,
        loadingAction: null,
        error: null,
        notice: normalized ? null : '暂无历史真实结果。',
        lastFailure: null,
      }));
    } catch (error) {
      if (isRequestCanceled(error) || !isLatestRequest(requestId)) return null;
      const failure = buildFailure('loadLatest', error, undefined, '读取最新真实结果失败');
      setState((prev) => ({
        ...prev,
        result: prev.latestRealResult,
        readiness: failure.run_readiness ?? prev.readiness,
        loading: false,
        loadingAction: null,
        error: failure.detail,
        notice: prev.latestRealResult ? PREVIOUS_REAL_RESULT_NOTICE : null,
        lastFailure: failure,
      }));
      console.error(error);
    }
  }, [beginRequest, isLatestRequest, updateState]);

  const runResearch = async (config: FactorLabRunConfig) => {
    const { requestId, signal } = beginRequest();
    updateState({
      loading: true,
      loadingAction: 'run',
      checkingReadiness: true,
      error: null,
      notice: null,
      lastFailure: null,
    });

    const { readiness, failure: readinessFailure } = await fetchReadiness(config, signal);
    if (!isLatestRequest(requestId)) return null;
    if (readinessFailure) {
      const failure: FactorLabFailureState = {
        action: 'runResearch',
        detail: readinessFailure.detail,
        error_code: readinessFailure.error_code,
        config,
        run_readiness: readiness ?? readinessFailure.run_readiness,
      };
      setState((prev) => ({
        ...prev,
        result: prev.latestRealResult,
        readiness: readiness ?? prev.readiness,
        checkingReadiness: false,
        loading: false,
        loadingAction: null,
        error: failure.detail,
        notice: prev.latestRealResult ? PREVIOUS_REAL_RESULT_NOTICE : null,
        lastFailure: failure,
      }));
      return null;
    }

    try {
      const submit = await apiPost<{ job_id: string }>('/api/factor-lab/jobs', config, { timeout: 15000, signal });
      const response = await pollJobResult<unknown>(`/api/research/jobs/${submit.job_id}`, `/api/research/jobs/${submit.job_id}/result`, { signal, timeoutMs: 60 * 60 * 1000 });
      if (!isLatestRequest(requestId)) return null;
      const normalized = normalizeFactorLabResult(response, config);
      if (!normalized) {
        throw new Error('后端未返回可展示的真实研究结果。');
      }
      setState((prev) => ({
        ...prev,
        result: normalized,
        latestRealResult: normalized,
        readiness: normalized.run_readiness ?? readiness ?? prev.readiness,
        checkingReadiness: false,
        loading: false,
        loadingAction: null,
        error: null,
        notice: null,
        lastFailure: null,
      }));
      return normalized;
    } catch (error) {
      if (isRequestCanceled(error) || !isLatestRequest(requestId)) return null;
      const failure = buildFailure('runResearch', error, config, '因子研究执行失败');
      setState((prev) => ({
        ...prev,
        result: prev.latestRealResult,
        readiness: failure.run_readiness ?? readiness ?? prev.readiness,
        checkingReadiness: false,
        loading: false,
        loadingAction: null,
        error: failure.detail,
        notice: prev.latestRealResult ? PREVIOUS_REAL_RESULT_NOTICE : null,
        lastFailure: failure,
      }));
      console.error(error);
      return null;
    }
  };

  const runBacktest = async (config: FactorLabRunConfig) => {
    const { requestId, signal } = beginRequest();
    updateState({ loading: true, loadingAction: 'backtest', error: null, notice: null, lastFailure: null });
    try {
      const response = await apiPost<unknown>('/api/factor-lab/backtest', buildBacktestRequest(config), { timeout: 180000, signal });
      if (!isLatestRequest(requestId)) return null;
      const backtest = normalizeBacktest(response);
      if (!backtest) {
        throw new Error('后端未返回有效的回测摘要。');
      }
      setState((prev) => {
        const baseResult = prev.result ?? prev.latestRealResult;
        const nextResult = baseResult ? { ...baseResult, backtest } : null;
        return {
          ...prev,
          result: nextResult ?? null,
          loading: false,
          loadingAction: null,
          error: null,
          notice: null,
          lastFailure: null,
        };
      });
      return backtest;
    } catch (error) {
      if (isRequestCanceled(error) || !isLatestRequest(requestId)) return null;
      const failure = buildFailure('runBacktest', error, config, 'ML 回测执行失败');
      let fallbackBacktest: ReturnType<typeof normalizeBacktest> = null;
      setState((prev) => {
        fallbackBacktest = prev.latestRealResult?.backtest ?? null;
        const baseResult = prev.result ?? prev.latestRealResult;
        const nextResult = baseResult ? { ...baseResult, backtest: fallbackBacktest } : null;
        return {
          ...prev,
          result: nextResult,
          readiness: failure.run_readiness ?? prev.readiness,
          loading: false,
          loadingAction: null,
          error: failure.detail,
          notice: fallbackBacktest ? PREVIOUS_REAL_RESULT_NOTICE : null,
          lastFailure: failure,
        };
      });
      console.error(error);
      return fallbackBacktest;
    }
  };

  const runStressTest = async (config: FactorLabRunConfig) => {
    const { requestId, signal } = beginRequest();
    updateState({ loading: true, loadingAction: 'stress', error: null, notice: null, lastFailure: null });
    try {
      const response = await apiPost<unknown>('/api/factor-lab/stress-test', buildStressTestRequest(config), { timeout: 240000, signal });
      if (!isLatestRequest(requestId)) return null;
      const payload = isRecord(response) ? response : {};
      const stressTest = normalizeStressTest(payload.stress_test);
      const selfIteration = normalizeSelfIteration(payload.self_iteration);
      const strategyLifecycle = normalizeStrategyLifecycle(payload.strategy_lifecycle);
      if (!stressTest) {
        throw new Error('后端未返回有效的三行情景测评结果。');
      }
      setState((prev) => {
        const baseResult = prev.result ?? prev.latestRealResult;
        const nextResult = baseResult ? {
          ...baseResult,
          stress_test: stressTest,
          self_iteration: selfIteration ?? baseResult.self_iteration ?? null,
          strategy_lifecycle: strategyLifecycle ?? baseResult.strategy_lifecycle ?? null,
        } : null;
        return {
          ...prev,
          result: nextResult,
          latestRealResult: nextResult ?? prev.latestRealResult,
          loading: false,
          loadingAction: null,
          error: null,
          notice: nextResult ? '三行情景测评已完成，候选版本门禁已刷新。' : '三行情景测评已完成，请先生成一次策略体检报告后再查看完整结论。',
          lastFailure: null,
        };
      });
      return stressTest;
    } catch (error) {
      if (isRequestCanceled(error) || !isLatestRequest(requestId)) return null;
      const failure = buildFailure('runStressTest', error, config, '三行情景测评执行失败');
      setState((prev) => ({
        ...prev,
        result: prev.latestRealResult,
        readiness: failure.run_readiness ?? prev.readiness,
        loading: false,
        loadingAction: null,
        error: failure.detail,
        notice: prev.latestRealResult ? PREVIOUS_REAL_RESULT_NOTICE : null,
        lastFailure: failure,
      }));
      console.error(error);
      return null;
    }
  };

  const runVersionAction = async (
    actionKey: string,
    path: string,
    body?: unknown,
    successNotice = '策略版本状态已更新。'
  ) => {
    const { requestId, signal } = beginRequest();
    updateState({ loading: true, loadingAction: null, versionActionLoading: actionKey, error: null, notice: null, lastFailure: null });
    try {
      await apiPost<unknown>(path, body, { timeout: 60000, signal });
      if (!isLatestRequest(requestId)) return null;
      const latest = await apiGet<unknown>('/api/factor-lab/results', { timeout: 20000, signal });
      if (!isLatestRequest(requestId)) return null;
      const normalized = normalizeFactorLabResult(latest, DEFAULT_FACTOR_LAB_RUN_CONFIG);
      setState((prev) => ({
        ...prev,
        result: normalized ?? prev.result,
        latestRealResult: normalized ?? prev.latestRealResult,
        readiness: normalized?.run_readiness ?? prev.readiness,
        loading: false,
        loadingAction: null,
        versionActionLoading: null,
        error: null,
        notice: successNotice,
        lastFailure: null,
      }));
      return normalized;
    } catch (error) {
      if (isRequestCanceled(error) || !isLatestRequest(requestId)) return null;
      const failure = buildFailure('versionAction', error, undefined, '策略版本操作失败');
      setState((prev) => ({
        ...prev,
        loading: false,
        loadingAction: null,
        versionActionLoading: null,
        error: failure.detail,
        notice: prev.latestRealResult ? PREVIOUS_REAL_RESULT_NOTICE : null,
        lastFailure: failure,
      }));
      console.error(error);
      return null;
    }
  };

  const promoteCurrentRun = async (runId: string, candidateFactor = 'ml_factor_ranker') => (
    runVersionAction(
      `promote:${runId}`,
      `/api/factor-lab/candidates/${encodeURIComponent(runId)}/promote`,
      {
        strategy_id: 'ai_ml',
        candidate_factor: candidateFactor,
        created_by: 'local_user',
        note: '从 Factor Lab 前端提升为候选策略版本',
      },
      '已生成候选策略版本。'
    )
  );

  const startShadow = async (versionId: string) => (
    runVersionAction(
      `shadow:${versionId}`,
      `/api/strategy-versions/${encodeURIComponent(versionId)}/shadow`,
      { user: 'local_user', note: '从 Factor Lab 前端启动影子观察' },
      '已启动影子观察账户。'
    )
  );

  const approveVersion = async (versionId: string) => (
    runVersionAction(
      `approve:${versionId}`,
      `/api/strategy-versions/${encodeURIComponent(versionId)}/approve`,
      { user: 'local_user', note: 'Factor Lab 门禁通过后审批' },
      '候选版本已审批。'
    )
  );

  const activateVersion = async (versionId: string, strategyId = 'ai_ml') => (
    runVersionAction(
      `activate:${versionId}`,
      `/api/strategies/${encodeURIComponent(strategyId)}/activate-version`,
      { version_id: versionId, user: 'local_user', note: '切换 Factor Lab 活动版本' },
      '活动版本已切换。'
    )
  );

  const rollbackVersion = async (strategyId = 'ai_ml') => (
    runVersionAction(
      `rollback:${strategyId}`,
      `/api/strategies/${encodeURIComponent(strategyId)}/rollback`,
      { user: 'local_user', reason: 'Factor Lab 前端请求回滚' },
      '策略已回滚到上一版本或基线。'
    )
  );

  const iterateVersion = async (versionId: string) => (
    runVersionAction(
      `iterate:${versionId}`,
      `/api/strategy-versions/${encodeURIComponent(versionId)}/iterate`,
      { user: 'local_user', note: '从 Factor Lab 前端创建候选定向迭代计划' },
      '已生成候选定向迭代计划。'
    )
  );

  // readiness 自动检查: 防抖 + 参数未变不重发 + 取消在途请求
  //
  // 这里用 useMemo 按「参与 readiness 检查的字段」派生一个稳定引用：
  //   - 字段没变 -> 返回同一个对象 -> 下面的 effect 不重跑（等价于旧的 configKey 去重）；
  //   - 任一字段变了 -> 新对象 -> effect 重跑、防抖计时器重置、旧请求 abort。
  // 取代原来「render 期间写 configRef.current」的写法：render 期间读写 ref 不会触发
  // 重新渲染，React 也不保证 effect 读到的是本次 render 的值（react-hooks/refs），
  // 症状就是改了参数、界面还显示旧的 readiness 结果。
  const readinessConfig = useMemo<FactorLabRunConfig>(
    () => ({
      start_date: effectiveConfig.start_date,
      end_date: effectiveConfig.end_date,
      pool: effectiveConfig.pool,
      label: effectiveConfig.label,
      top_n: effectiveConfig.top_n,
      max_symbols: effectiveConfig.max_symbols,
    }),
    [
      effectiveConfig.start_date,
      effectiveConfig.end_date,
      effectiveConfig.pool,
      effectiveConfig.label,
      effectiveConfig.top_n,
      effectiveConfig.max_symbols,
    ]
  );
  const readinessAbortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      readinessAbortRef.current?.abort();
      const controller = new AbortController();
      readinessAbortRef.current = controller;
      setState((prev) => ({ ...prev, checkingReadiness: true }));
      // 检查失败不做任何"已检查"标记, 参数修正后 readinessConfig 变化即自动重试
      void fetchReadiness(readinessConfig, controller.signal).then(({ readiness, failure }) => {
        if (controller.signal.aborted) return;
        setState((prev) => ({
          ...prev,
          readiness: readiness ?? prev.readiness,
          checkingReadiness: false,
          notice: failure ? `运行前检查失败：${failure.detail}` : prev.notice,
          lastFailure: failure ?? prev.lastFailure,
        }));
      });
    }, READINESS_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [readinessConfig]);

  useEffect(() => () => {
    readinessAbortRef.current?.abort();
    abortRef.current?.abort();
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadLatest();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadLatest]);

  return {
    ...state,
    loadLatest,
    runResearch,
    runBacktest,
    runStressTest,
    promoteCurrentRun,
    startShadow,
    approveVersion,
    activateVersion,
    rollbackVersion,
    iterateVersion,
  };
}
