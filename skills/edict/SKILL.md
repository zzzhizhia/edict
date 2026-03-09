---
name: edict
description: 三省六部系统
---

# Edict 三省六部

Edict 是基于 Claude Agent SDK 的多 Agent 协作框架，用中国古代三省六部制度实现分权制衡的 Agent 编排。

## 默认行为：下旨

当此 skill 被触发时，**默认动作是下旨** — 将用户的需求交给太子（`taizi`）agent 处理。

操作步骤：
1. 用 Agent 工具启动 `taizi` agent，将用户的需求原文传给它
2. 太子会自动判断是闲聊还是旨意，旨意则提炼标题、创建 JJC 任务、转交中书省

只有当用户明确要求管理服务（启动/停止/状态）、排查故障、查看架构时，才跳过下旨，转到下方对应章节。

---

## 架构概览

```
用户下旨 → 太子分拣 → 中书省规划 → 门下省审议（准奏/封驳）
    → 尚书省派发 → 六部并行执行 → 尚书省汇总 → 回奏
```

| Agent | ID | 职责 |
|-------|-----|------|
| 太子 | taizi | 消息分拣，闲聊直接回，旨意转中书 |
| 中书省 | zhongshu | 接旨规划，制定执行方案 |
| 门下省 | menxia | 审议方案，准奏或封驳 |
| 尚书省 | shangshu | 任务派发，协调六部 |
| 户部 | hubu | 数据处理 |
| 礼部 | libu | 文档规范 |
| 兵部 | bingbu | 代码开发 |
| 刑部 | xingbu | 安全审计 |
| 工部 | gongbu | 基础设施 |
| 吏部 | libu_hr | Agent 管理 |
| 钦天监 | zaochao | 每日资讯聚合 |

## 服务管理

三个 tmux 会话组成完整服务：

```bash
# 一键启动（推荐）
cd /Users/zzzhizhi/Developer/zzzhizhia/edict && make start

# 一键停止
make stop

# 查看状态
make status

# 查看日志
make logs
```

单独管理：

```bash
make backend    # FastAPI API (port 8000)
make dashboard  # 看板服务 (port 17891)
make loop       # 数据刷新循环 (15s)
```

服务启动后打开看板：`http://127.0.0.1:17891`

## 任务管理（kanban_update.py）

Agent 通过 CLI 工具操作看板：

```bash
cd /Users/zzzhizhi/Developer/zzzhizhia/edict

# 创建旨意
python3 scripts/kanban_update.py create <任务ID> "<标题>" <目标Agent> <部门名> <角色> "<备注>"
# 示例：
python3 scripts/kanban_update.py create JJC-20260310-001 "设计用户系统" Zhongshu 中书省 中书令 "需要OAuth2支持"

# 更新状态（触发状态机流转）
python3 scripts/kanban_update.py state <任务ID> <新状态> "<备注>"
# 示例：
python3 scripts/kanban_update.py state JJC-20260310-001 Menxia "方案提交审议"

# 记录流转日志
python3 scripts/kanban_update.py flow <任务ID> "<来源部门>" "<目标部门>" "<说明>"

# 标记完成
python3 scripts/kanban_update.py done <任务ID> "<产出>" "<摘要>"

# 叫停任务
python3 scripts/kanban_update.py halt <任务ID> "<原因>"
```

任务状态机：`Taizi → Zhongshu → Menxia → Assigned → Doing → Review → Done`

## 关键文件路径

| 文件 | 用途 |
|------|------|
| `Makefile` | 服务启停管理 |
| `dashboard/server.py` | 看板 HTTP 服务（零依赖） |
| `dashboard/dashboard.html` | 看板前端（单文件，零 CDN） |
| `edict/backend/app/main.py` | FastAPI 入口 |
| `edict/backend/app/services/agent_runner.py` | Agent 执行引擎 |
| `scripts/kanban_update.py` | 看板 CLI 工具 |
| `scripts/run_loop.sh` | 数据刷新循环 |
| `scripts/sync_officials_stats.py` | Agent 统计 |
| `data/live_status.json` | 当前任务状态 |
| `data/agent_config.json` | Agent 配置缓存 |
| `data/officials_stats.json` | Token 排行榜 |
| `agents/*.md` | Agent 人格配置（源） |
| `~/.claude/agents/edict/*.md` | Agent 人格配置（运行时） |

## 模型切换

通过看板 UI 或直接修改 `~/.claude/settings.json` 中的 agents 配置。修改后 `scripts/apply_model_changes.py` 会在下一个刷新周期自动应用。

## 故障排查

### 服务未启动
```bash
make status          # 检查哪个服务挂了
make start           # 重新启动全部
```

### 数据不更新
```bash
# 检查刷新循环
tmux ls | grep edict-loop
# 手动刷新
python3 scripts/refresh_live_data.py
```

### Agent 无响应
```bash
# 检查 Backend 日志
tail -50 logs/backend.log
# 检查 Agent 配置是否正确同步
python3 scripts/sync_agent_config.py
```

### 任务卡住
```bash
# 手动触发巡检（检测超过 180s 无进展的任务）
curl -s -X POST http://127.0.0.1:17891/api/scheduler-scan \
  -H 'Content-Type: application/json' -d '{"thresholdSec":180}'
```

## 开发调试

```bash
# 运行测试
cd /Users/zzzhizhi/Developer/zzzhizhia/edict
python3 -m pytest tests/

# 检查 Python 语法
python3 -m py_compile edict/backend/app/main.py

# 直接访问 Backend API
curl http://127.0.0.1:8000/docs   # Swagger 文档
curl http://127.0.0.1:8000/api/admin/active-agents

# 查看 tmux 会话内容
tmux attach -t edict-backend
# Ctrl+B D 退出 tmux
```
