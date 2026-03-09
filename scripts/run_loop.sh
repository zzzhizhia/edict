#!/bin/bash
# 三省六部 · 数据刷新循环
# 用法: ./run_loop.sh [间隔秒数]  (默认 15)

set -euo pipefail

SCRIPT_DIR="${EDICT_HOME:-$HOME/.claude/edict}/scripts"
INTERVAL="${1:-15}"
LOG="/tmp/sansheng_liubu_refresh.log"
MAX_LOG_SIZE=$((10 * 1024 * 1024))  # 10MB

# 注意：单实例保护由 Makefile tmux 会话管理，此处不再使用 PID 文件

# ── 日志轮转 ──
rotate_log() {
  if [[ -f "$LOG" ]] && (( $(stat -f%z "$LOG" 2>/dev/null || stat -c%s "$LOG" 2>/dev/null || echo 0) > MAX_LOG_SIZE )); then
    mv "$LOG" "${LOG}.1"
    echo "$(date '+%H:%M:%S') [loop] 日志已轮转" > "$LOG"
  fi
}

SCAN_INTERVAL="${2:-120}"  # 巡检间隔(秒), 默认 120
SCAN_COUNTER=0
SCRIPT_TIMEOUT=30  # 单个脚本最大执行时间(秒)

echo "🏛️  三省六部数据刷新循环启动 (PID=$$)"
echo "   脚本目录: $SCRIPT_DIR"
echo "   间隔: ${INTERVAL}s"
echo "   巡检间隔: ${SCAN_INTERVAL}s"
echo "   脚本超时: ${SCRIPT_TIMEOUT}s"
echo "   日志: $LOG"
echo "   按 Ctrl+C 停止"

# ── 安全执行（带超时保护）──
safe_run() {
  local script="$1"
  if command -v timeout &>/dev/null; then
    timeout "$SCRIPT_TIMEOUT" python3 "$script" >> "$LOG" 2>&1 || {
      local rc=$?
      if [[ $rc -eq 124 ]]; then
        echo "$(date '+%H:%M:%S') [loop] ⚠️ 脚本超时(${SCRIPT_TIMEOUT}s): $script" >> "$LOG"
      fi
    }
  else
    python3 "$script" >> "$LOG" 2>&1 || true
  fi
}

while true; do
  rotate_log
  # NOTE: sync_from_openclaw_runtime.py 已移除 — Agent SDK 事件实时流入，不再需要扫描 session JSONL
  safe_run "$SCRIPT_DIR/sync_agent_config.py"
  safe_run "$SCRIPT_DIR/apply_model_changes.py"
  safe_run "$SCRIPT_DIR/sync_officials_stats.py"
  safe_run "$SCRIPT_DIR/refresh_live_data.py"

  # 定期巡检：检测卡住的任务并自动重试
  SCAN_COUNTER=$((SCAN_COUNTER + INTERVAL))
  if (( SCAN_COUNTER >= SCAN_INTERVAL )); then
    SCAN_COUNTER=0
    curl -s -X POST http://127.0.0.1:17891/api/scheduler-scan \
      -H 'Content-Type: application/json' -d '{"thresholdSec":180}' >> "$LOG" 2>&1 || true
  fi

  sleep "$INTERVAL"
done
