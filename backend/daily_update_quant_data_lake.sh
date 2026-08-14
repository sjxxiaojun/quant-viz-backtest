#!/bin/zsh
# 路径基于脚本自身位置推导；优先使用项目 venv 解释器。
BACKEND_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="$BACKEND_DIR/venv/bin/python3"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi
exec "$PYTHON_BIN" "$BACKEND_DIR/daily_update_quant_data_lake.py" "$@"
