/**
 * D-12: ViewModel 状态与海量数据解耦 Store
 *
 * 设计原则：
 * 1. React 组件树仅持有轻量 UI ViewModel 状态（激活视图、选中的时间窗口、指标开关、对比项）。
 * 2. 海量 Bar 数组 / 净值序列 / 原始交易数据存储在 React 渲染树外部（DataCache），
 *    避免 10 万+ 数据点触发深度 Diff 和垃圾回收开销。
 */

export interface ViewState {
  activeView: string;
  selectedStrategy: string;
  startDate: string;
  endDate: string;
  selectedPool: string;
  benchmarkCode: string;
  zoomRange: [number, number]; // [startPercent, endPercent]
  activeMetrics: string[];
}

export type ViewListener = (state: ViewState) => void;

class ViewModelStore {
  private state: ViewState = {
    activeView: 'mall',
    selectedStrategy: 'power_energy',
    startDate: '2023-01-01',
    endDate: '2024-12-31',
    selectedPool: 'auto',
    benchmarkCode: '000300',
    zoomRange: [0, 100],
    activeMetrics: ['total_return', 'sharpe', 'max_drawdown', 'win_rate'],
  };

  private listeners: Set<ViewListener> = new Set();

  // 外部海量数据缓存（不参与 React 组件状态响应式追踪，杜绝万级数据重渲染掉帧）
  private heavyDataCache: Map<string, Float64Array | any[]> = new Map();

  public getState(): ViewState {
    return this.state;
  }

  public setState(partial: Partial<ViewState>): void {
    this.state = { ...this.state, ...partial };
    this.notify();
  }

  public subscribe(listener: ViewListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify(): void {
    for (const listener of this.listeners) {
      listener(this.state);
    }
  }

  // 外部海量数据存取
  public setHeavyData(key: string, data: Float64Array | any[]): void {
    this.heavyDataCache.set(key, data);
  }

  public getHeavyData<T = any>(key: string): T | undefined {
    return this.heavyDataCache.get(key) as T | undefined;
  }

  public clearHeavyData(): void {
    this.heavyDataCache.clear();
  }
}

export const viewStore = new ViewModelStore();
