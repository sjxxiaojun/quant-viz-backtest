#!/bin/bash
export PATH=$PATH:/Users/gdxj/.local/bin
cd /Users/gdxj/quant-viz-backtest/frontend
exec /Users/gdxj/.local/bin/npm run dev -- --force >> /Users/gdxj/quant-viz-backtest/frontend/frontend.log 2>&1
