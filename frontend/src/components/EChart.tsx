import React, { useEffect, useRef } from 'react';
import { BarChart, LineChart, PieChart, CandlestickChart } from 'echarts/charts';
import {
  GridComponent,
  LegendComponent,
  MarkPointComponent,
  TooltipComponent,
  DataZoomComponent,
} from 'echarts/components';
import type { EChartsCoreOption } from 'echarts/core';
import * as echarts from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { incrementalRenderer } from '../chart/incrementalRenderer';

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  CandlestickChart,
  GridComponent,
  LegendComponent,
  MarkPointComponent,
  TooltipComponent,
  DataZoomComponent,
  CanvasRenderer,
]);

interface EChartProps {
  option: EChartsCoreOption;
  style?: React.CSSProperties;
  className?: string;
  largeDataSeries?: { seriesIndex: number; data: any[] }[];
}

export function EChart({ option, style, className, largeDataSeries }: EChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!containerRef.current) return undefined;
    const chart = echarts.init(containerRef.current, undefined, { renderer: 'canvas' });
    chartRef.current = chart;
    return () => {
      incrementalRenderer.cancel();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chartRef.current) return;
    if (largeDataSeries && largeDataSeries.length > 0) {
      incrementalRenderer.renderSeries(chartRef.current, option, largeDataSeries);
    } else {
      chartRef.current.setOption(option, true);
    }
  }, [option, largeDataSeries]);

  useEffect(() => {
    if (!containerRef.current) return undefined;
    const observer = new ResizeObserver(() => {
      chartRef.current?.resize();
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  return <div ref={containerRef} className={className} style={style} />;
}
