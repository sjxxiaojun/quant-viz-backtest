#!/bin/bash
export PATH=$PATH:/Users/USER/.local/bin
cd /Users/USER/quant-viz-backtest/frontend
exec /Users/USER/.local/bin/npm run dev -- --force >> /Users/USER/quant-viz-backtest/frontend/frontend.log 2>&1
