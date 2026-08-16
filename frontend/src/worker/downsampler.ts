/**
 * D-13: 降采样服务客户端 (Downsample Client)
 * 自动管理 Web Worker 生命周期与 Transferable 零拷贝通道。
 */

import { downsampleKLTTB } from './klttb.worker';

export interface BarData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export class DownsamplerClient {
  private worker: Worker | null = null;
  private reqId = 0;
  private pendingResolvers = new Map<number, (res: Float64Array) => void>();

  constructor() {
    this.initWorker();
  }

  private initWorker() {
    if (typeof window !== 'undefined' && typeof Worker !== 'undefined') {
      try {
        this.worker = new Worker(
          new URL('./klttb.worker.ts', import.meta.url),
          { type: 'module' }
        );
        this.worker.onmessage = (e: MessageEvent<{ id: number; buffer: ArrayBuffer }>) => {
          const { id, buffer } = e.data;
          const resolve = this.pendingResolvers.get(id);
          if (resolve) {
            this.pendingResolvers.delete(id);
            resolve(new Float64Array(buffer));
          }
        };
      } catch {
        this.worker = null;
      }
    }
  }

  /**
   * 将对象数组打包为连续的 Float64Array (每行 7 项)
   */
  public packBars(bars: BarData[]): Float64Array {
    const stride = 7;
    const packed = new Float64Array(bars.length * stride);
    for (let i = 0; i < bars.length; i++) {
      const b = bars[i];
      const offset = i * stride;
      packed[offset + 0] = b.time;
      packed[offset + 1] = b.open;
      packed[offset + 2] = b.high;
      packed[offset + 3] = b.low;
      packed[offset + 4] = b.close;
      packed[offset + 5] = b.volume;
      packed[offset + 6] = i; // 原始下标
    }
    return packed;
  }

  /**
   * 解包为 Bar 结构数组
   */
  public unpackBars(packed: Float64Array): Array<BarData & { originalIndex: number }> {
    const stride = 7;
    const count = Math.floor(packed.length / stride);
    const result = new Array(count);
    for (let i = 0; i < count; i++) {
      const offset = i * stride;
      result[i] = {
        time: packed[offset + 0],
        open: packed[offset + 1],
        high: packed[offset + 2],
        low: packed[offset + 3],
        close: packed[offset + 4],
        volume: packed[offset + 5],
        originalIndex: packed[offset + 6],
      };
    }
    return result;
  }

  /**
   * 异步降采样：优先使用 Web Worker Transferable 零拷贝，若环境不支持则回退主线程
   */
  public async downsample(packed: Float64Array, targetCount: number): Promise<Float64Array> {
    if (packed.length / 7 <= targetCount) {
      return packed;
    }

    if (this.worker) {
      const id = ++this.reqId;
      return new Promise<Float64Array>((resolve) => {
        this.pendingResolvers.set(id, resolve);
        // Transferable 模式：转移 buffer 控制权
        const copy = new Float64Array(packed);
        this.worker!.postMessage(
          {
            id,
            buffer: copy.buffer,
            targetCount,
          },
          [copy.buffer]
        );
      });
    }

    // 主线程回退
    return Promise.resolve(downsampleKLTTB(packed, targetCount));
  }

  public destroy() {
    this.worker?.terminate();
    this.worker = null;
    this.pendingResolvers.clear();
  }
}

export const downsampler = new DownsamplerClient();
