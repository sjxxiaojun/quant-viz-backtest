/**
 * D-14: ECharts rAF appendData 增量渲染调度器
 *
 * 核心特性：
 * 1. 阈值自动分流：bar < 5000 全量快速渲染；bar >= 5000 启用 rAF 增量通道。
 * 2. 基于 requestAnimationFrame 的时间切片分批加载，防止万级数据阻塞主线程导致 UI 冻结。
 * 3. 丝滑保证：缩放平移保持 60fps 刷新率。
 */

import type { ECharts, EChartsCoreOption } from 'echarts/core';

export interface IncrementalRenderOptions {
  threshold?: number; // 默认 5000
  chunkSize?: number;  // 每批次条数，默认 2000
  onProgress?: (renderedRatio: number) => void;
  onComplete?: () => void;
}

export class IncrementalChartRenderer {
  private rafId: number | null = null;
  private isRendering = false;

  /**
   * 执行自适应分批渲染
   */
  public renderSeries(
    chart: ECharts,
    baseOption: EChartsCoreOption,
    largeDataSeries: { seriesIndex: number; data: unknown[] }[],
    options: IncrementalRenderOptions = {}
  ): void {
    this.cancel();

    const threshold = options.threshold ?? 5000;
    const chunkSize = options.chunkSize ?? 2000;

    // 检查是否有 series 达到大容量阈值
    const maxLen = Math.max(0, ...largeDataSeries.map((s) => s.data.length));

    if (maxLen < threshold) {
      // 全量渲染通道
      chart.setOption(baseOption, true);
      options.onProgress?.(1.0);
      options.onComplete?.();
      return;
    }

    // 增量渲染通道：首先下发框架与首批数据
    this.isRendering = true;

    // 准备首批数据
    const initialSeries = largeDataSeries.map((s) => ({
      seriesIndex: s.seriesIndex,
      data: s.data.slice(0, chunkSize),
    }));

    // 浅拷贝 option 并注入首批数据
    const startOption = { ...baseOption } as EChartsCoreOption & { series?: unknown };
    if (Array.isArray(startOption.series)) {
      startOption.series = startOption.series.map((ser, idx: number) => {
        const found = initialSeries.find((init) => init.seriesIndex === idx);
        return found ? { ...ser, data: found.data } : ser;
      });
    }

    chart.setOption(startOption, true);

    let currentOffset = chunkSize;

    const step = () => {
      if (!this.isRendering || currentOffset >= maxLen) {
        this.isRendering = false;
        options.onProgress?.(1.0);
        options.onComplete?.();
        return;
      }

      // 针对每个大数据 series 执行增量追加
      for (const item of largeDataSeries) {
        if (currentOffset < item.data.length) {
          const chunk = item.data.slice(currentOffset, currentOffset + chunkSize);
          if (chunk.length > 0 && typeof chart.appendData === 'function') {
            chart.appendData({
              seriesIndex: item.seriesIndex,
              data: chunk,
            });
          }
        }
      }

      currentOffset += chunkSize;
      options.onProgress?.(Math.min(1.0, currentOffset / maxLen));

      this.rafId = requestAnimationFrame(step);
    };

    this.rafId = requestAnimationFrame(step);
  }

  public cancel(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    this.isRendering = false;
  }
}

export const incrementalRenderer = new IncrementalChartRenderer();
