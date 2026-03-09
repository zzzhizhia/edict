#!/bin/bash
# ══════════════════════════════════════════════════════════════
# 三省六部 · Claude Code Multi-Agent System 一键安装脚本
# ══════════════════════════════════════════════════════════════
set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_HOME="$HOME/.claude"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

banner() {
  echo ""
  echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
  echo -e "${BLUE}║  🏛️  三省六部 · Claude Code Multi-Agent  ║${NC}"
  echo -e "${BLUE}║       安装向导                            ║${NC}"
  echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}"
  echo ""
}

log()   { echo -e "${GREEN}✅ $1${NC}"; }
warn()  { echo -e "${YELLOW}⚠️  $1${NC}"; }
error() { echo -e "${RED}❌ $1${NC}"; }
info()  { echo -e "${BLUE}ℹ️  $1${NC}"; }

# ── Step 0: 依赖检查 ──────────────────────────────────────────
check_deps() {
  info "检查依赖..."

  if ! command -v claude &>/dev/null; then
    error "未找到 claude CLI。请先安装 Claude Code: https://docs.anthropic.com/en/docs/claude-code"
    exit 1
  fi
  log "Claude Code CLI: $(claude --version 2>/dev/null || echo 'OK')"

  if ! command -v python3 &>/dev/null; then
    error "未找到 python3"
    exit 1
  fi
  log "Python3: $(python3 --version)"
}

# ── Step 0.5: 备份已有 Agent 数据 ──────────────────────────────
backup_existing() {
  AGENTS_DIR="$CLAUDE_HOME/agents"
  BACKUP_DIR="$CLAUDE_HOME/backups/pre-install-$(date +%Y%m%d-%H%M%S)"
  HAS_EXISTING=false

  # 检查是否有已存在的 agent .md 文件
  if [ -d "$AGENTS_DIR" ]; then
    for f in "$AGENTS_DIR"/*.md; do
      if [ -f "$f" ]; then
        HAS_EXISTING=true
        break
      fi
    done
  fi

  if $HAS_EXISTING; then
    info "检测到已有 Agent 配置，自动备份中..."
    mkdir -p "$BACKUP_DIR"

    # 备份所有 agent .md 文件
    cp -R "$AGENTS_DIR" "$BACKUP_DIR/agents"

    log "已备份到: $BACKUP_DIR"
    info "如需恢复，运行: cp -R $BACKUP_DIR/agents/* $AGENTS_DIR/"
  fi
}

# ── Step 1: 创建 Agent 配置 ──────────────────────────────────
create_workspaces() {
  info "创建 Agent 配置..."

  AGENTS_DIR="$CLAUDE_HOME/agents"
  mkdir -p "$AGENTS_DIR"

  AGENTS=(taizi zhongshu menxia shangshu hubu libu bingbu xingbu gongbu libu_hr zaochao)
  for agent in "${AGENTS[@]}"; do
    if [ -f "$REPO_DIR/agents/$agent/SOUL.md" ]; then
      AGENT_MD="$AGENTS_DIR/$agent.md"
      if [ -f "$AGENT_MD" ]; then
        # 已存在的配置，先备份再覆盖
        cp "$AGENT_MD" "$AGENT_MD.bak.$(date +%Y%m%d-%H%M%S)"
        warn "已备份旧配置 → $AGENT_MD.bak.*"
      fi

      # 生成 agent .md 文件（frontmatter + SOUL.md 内容）
      SOUL_CONTENT=$(sed "s|__REPO_DIR__|$REPO_DIR|g" "$REPO_DIR/agents/$agent/SOUL.md")
      cat > "$AGENT_MD" << AGENT_EOF
---
name: ${agent}
description: 三省六部 ${agent} agent
tools: Read, Grep, Glob, Bash, Edit, Write
model: sonnet
---

${SOUL_CONTENT}
AGENT_EOF
    fi
    log "Agent 配置已创建: $AGENTS_DIR/$agent.md"
  done
}

# ── Step 2: 确认 Agents 就位 ─────────────────────────────────
register_agents() {
  info "确认三省六部 Agents 配置..."

  AGENTS_DIR="$CLAUDE_HOME/agents"
  AGENTS=(taizi zhongshu menxia shangshu hubu libu bingbu xingbu gongbu libu_hr zaochao)

  all_ok=true
  for agent in "${AGENTS[@]}"; do
    if [ -f "$AGENTS_DIR/$agent.md" ]; then
      log "  ✓ $agent.md"
    else
      warn "  ✗ $agent.md 未找到"
      all_ok=false
    fi
  done

  if $all_ok; then
    log "所有 Agent 配置已就位"
  else
    warn "部分 Agent 配置缺失，请检查 agents/ 目录下的 SOUL.md 文件"
  fi
}

# ── Step 3: 初始化 Data ─────────────────────────────────────
init_data() {
  info "初始化数据目录..."

  mkdir -p "$REPO_DIR/data"

  # 初始化空文件
  for f in live_status.json agent_config.json model_change_log.json; do
    if [ ! -f "$REPO_DIR/data/$f" ]; then
      echo '{}' > "$REPO_DIR/data/$f"
    fi
  done
  echo '[]' > "$REPO_DIR/data/pending_model_changes.json"

  # 初始任务文件
  if [ ! -f "$REPO_DIR/data/tasks_source.json" ]; then
    python3 << 'PYEOF'
import json, pathlib
tasks = [
    {
        "id": "JJC-DEMO-001",
        "title": "🎉 系统初始化完成",
        "official": "工部尚书",
        "org": "工部",
        "state": "Done",
        "now": "三省六部系统已就绪",
        "eta": "-",
        "block": "无",
        "output": "",
        "ac": "系统正常运行",
        "flow_log": [
            {"at": "2024-01-01T00:00:00Z", "from": "皇上", "to": "中书省", "remark": "下旨初始化三省六部系统"},
            {"at": "2024-01-01T00:01:00Z", "from": "中书省", "to": "门下省", "remark": "规划方案提交审核"},
            {"at": "2024-01-01T00:02:00Z", "from": "门下省", "to": "尚书省", "remark": "✅ 准奏"},
            {"at": "2024-01-01T00:03:00Z", "from": "尚书省", "to": "工部", "remark": "派发：系统初始化"},
            {"at": "2024-01-01T00:04:00Z", "from": "工部", "to": "尚书省", "remark": "✅ 完成"},
        ]
    }
]
p = pathlib.Path(__file__).parent if '__file__' in dir() else pathlib.Path('.')
# Write to data dir
import os
data_dir = pathlib.Path(os.environ.get('REPO_DIR', '.')) / 'data'
data_dir.mkdir(exist_ok=True)
(data_dir / 'tasks_source.json').write_text(json.dumps(tasks, ensure_ascii=False, indent=2))
print('tasks_source.json 已初始化')
PYEOF
  fi

  log "数据目录初始化完成: $REPO_DIR/data"
}

# ── Step 4: 构建前端 ──────────────────────────────────────────
build_frontend() {
  info "构建 React 前端..."

  if ! command -v node &>/dev/null; then
    warn "未找到 node，跳过前端构建。看板将使用预构建版本（如果存在）"
    warn "请安装 Node.js 18+ 后运行: cd edict/frontend && npm install && npm run build"
    return
  fi

  if [ -f "$REPO_DIR/edict/frontend/package.json" ]; then
    cd "$REPO_DIR/edict/frontend"
    npm install --silent 2>/dev/null || npm install
    npm run build 2>/dev/null
    cd "$REPO_DIR"
    if [ -f "$REPO_DIR/dashboard/dist/index.html" ]; then
      log "前端构建完成: dashboard/dist/"
    else
      warn "前端构建可能失败，请手动检查"
    fi
  else
    warn "未找到 edict/frontend/package.json，跳过前端构建"
  fi
}

# ── Step 5: 首次数据同步 ────────────────────────────────────
first_sync() {
  info "执行首次数据同步..."
  cd "$REPO_DIR"

  REPO_DIR="$REPO_DIR" python3 scripts/sync_agent_config.py || warn "sync_agent_config 有警告"
  python3 scripts/refresh_live_data.py || warn "refresh_live_data 有警告"

  log "首次同步完成"
}

# ── Main ────────────────────────────────────────────────────
banner
check_deps
backup_existing
create_workspaces
register_agents
init_data
build_frontend
first_sync

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  🎉  三省六部安装完成！                          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "下一步："
echo "  1. 启动数据刷新循环:  bash scripts/run_loop.sh &"
echo "  2. 启动看板服务器:    python3 dashboard/server.py"
echo "  3. 打开看板:          http://127.0.0.1:7891"
echo ""
info "文档: docs/getting-started.md"
