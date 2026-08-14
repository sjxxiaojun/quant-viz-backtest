#!/bin/bash
# 所有路径基于脚本自身位置推导，避免绑定到某台机器的绝对路径。
BACKEND_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BACKEND_DIR"

LOCK_DIR="/tmp/quant-viz-backend-8080.lock"
HEALTH_URL="http://127.0.0.1:8080/healthz"
SERVICE_SIGNATURE='"service":"quant-viz-backtest"'

if curl --max-time 1 --fail --silent "$HEALTH_URL" | tr -d '[:space:]' | grep -q "$SERVICE_SIGNATURE"; then
  exit 0
fi

if lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port 8080 is occupied by a non quant-viz-backtest service." >&2
  exit 1
fi

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  lock_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null)"
  if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
    exit 0
  fi
  rm -rf "$LOCK_DIR"
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    exit 0
  fi
fi

echo "$$" > "$LOCK_DIR/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT

if curl --max-time 1 --fail --silent "$HEALTH_URL" | tr -d '[:space:]' | grep -q "$SERVICE_SIGNATURE"; then
  exit 0
fi

if lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port 8080 is occupied by a non quant-viz-backtest service." >&2
  exit 1
fi

ENV_FILE="$BACKEND_DIR/.env.local"
if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

# backend.log 由应用内 RotatingFileHandler 负责轮转写入；stdout/stderr 单独落盘避免双写同一文件。
exec env PYTHONUNBUFFERED=1 "$BACKEND_DIR/venv/bin/python3" -m uvicorn main:app --host 127.0.0.1 --port 8080 >> "$BACKEND_DIR/backend_stdout.log" 2>> "$BACKEND_DIR/backend_stderr.log"
