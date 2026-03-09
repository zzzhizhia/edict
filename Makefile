.PHONY: start stop status backend dashboard loop install logs

BACKEND_PORT ?= 8000
DASHBOARD_PORT ?= 17891
ROOT_DIR := $(shell pwd)
EDICT_HOME ?= $(HOME)/.claude/edict
LOG_DIR := $(ROOT_DIR)/logs
PYTHON := $(ROOT_DIR)/.venv/bin/python3

# tmux session 名称
S_BACKEND := edict-backend
S_DASHBOARD := edict-dashboard
S_LOOP := edict-loop

# ── 一键启动所有服务 ──
start:
	@mkdir -p $(LOG_DIR)
	@echo "🏛️  三省六部 · 启动服务..."
	@$(MAKE) -s backend
	@$(MAKE) -s loop
	@$(MAKE) -s dashboard
	@echo ""
	@echo "✅ 所有服务已启动"
	@echo "   看板: http://127.0.0.1:$(DASHBOARD_PORT)"
	@echo "   API:  http://127.0.0.1:$(BACKEND_PORT)"
	@echo ""
	@echo "停止: make stop | 状态: make status | 日志: make logs"

# ── Backend API ──
backend:
	@if tmux has-session -t $(S_BACKEND) 2>/dev/null; then \
		echo "⏭️  Backend 已在运行 (tmux: $(S_BACKEND))"; \
	else \
		tmux new-session -d -s $(S_BACKEND) \
			"cd $(ROOT_DIR)/edict/backend && $(PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port $(BACKEND_PORT) 2>&1 | tee -a $(LOG_DIR)/backend.log"; \
		echo "✅ Backend 启动 (tmux: $(S_BACKEND), port $(BACKEND_PORT))"; \
	fi

# ── Dashboard 看板 ──
dashboard:
	@if tmux has-session -t $(S_DASHBOARD) 2>/dev/null; then \
		echo "⏭️  Dashboard 已在运行 (tmux: $(S_DASHBOARD))"; \
	else \
		tmux new-session -d -s $(S_DASHBOARD) \
			"cd $(ROOT_DIR) && EDICT_HOME=$(EDICT_HOME) $(PYTHON) dashboard/server.py --port $(DASHBOARD_PORT) 2>&1 | tee -a $(LOG_DIR)/dashboard.log"; \
		echo "✅ Dashboard 启动 (tmux: $(S_DASHBOARD), port $(DASHBOARD_PORT))"; \
	fi

# ── 数据刷新循环 ──
loop:
	@if tmux has-session -t $(S_LOOP) 2>/dev/null; then \
		echo "⏭️  Loop 已在运行 (tmux: $(S_LOOP))"; \
	else \
		tmux new-session -d -s $(S_LOOP) \
			"cd $(ROOT_DIR) && EDICT_HOME=$(EDICT_HOME) bash $(EDICT_HOME)/scripts/run_loop.sh 2>&1 | tee -a $(LOG_DIR)/loop.log"; \
		echo "✅ Loop 启动 (tmux: $(S_LOOP))"; \
	fi

# ── 停止所有服务 ──
stop:
	@echo "🛑 停止服务..."
	@for svc in $(S_BACKEND) $(S_DASHBOARD) $(S_LOOP); do \
		if tmux has-session -t $$svc 2>/dev/null; then \
			tmux kill-session -t $$svc; \
			echo "  ✅ $$svc 已停止"; \
		else \
			echo "  ⚪ $$svc 未运行"; \
		fi; \
	done

# ── 查看状态 ──
status:
	@for svc in $(S_BACKEND) $(S_DASHBOARD) $(S_LOOP); do \
		if tmux has-session -t $$svc 2>/dev/null; then \
			echo "🟢 $$svc"; \
		else \
			echo "🔴 $$svc"; \
		fi; \
	done

# ── 查看日志 ──
logs:
	@tail -f $(LOG_DIR)/backend.log $(LOG_DIR)/dashboard.log $(LOG_DIR)/loop.log

# ── 安装 ──
install:
	@mkdir -p $(LOG_DIR)
	bash install.sh
