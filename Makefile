.PHONY: start stop status backend dashboard loop install

BACKEND_PORT ?= 8000
DASHBOARD_PORT ?= 17891
ROOT_DIR := $(shell pwd)
PID_DIR := $(ROOT_DIR)/.pids
LOG_DIR := $(ROOT_DIR)/logs

# ── 一键启动所有服务 ──
start:
	@mkdir -p $(PID_DIR) $(LOG_DIR)
	@echo "🏛️  三省六部 · 启动服务..."
	@$(MAKE) -s backend
	@$(MAKE) -s loop
	@$(MAKE) -s dashboard
	@echo ""
	@echo "✅ 所有服务已启动"
	@echo "   看板: http://127.0.0.1:$(DASHBOARD_PORT)"
	@echo "   API:  http://127.0.0.1:$(BACKEND_PORT)"
	@echo ""
	@echo "停止: make stop"

# ── Backend API ──
backend:
	@mkdir -p $(PID_DIR) $(LOG_DIR)
	@if [ -f $(PID_DIR)/backend.pid ] && kill -0 $$(cat $(PID_DIR)/backend.pid) 2>/dev/null; then \
		echo "⏭️  Backend 已在运行 (PID $$(cat $(PID_DIR)/backend.pid))"; \
	else \
		cd $(ROOT_DIR)/edict/backend && \
		nohup python3 -m uvicorn app.main:app --host 127.0.0.1 --port $(BACKEND_PORT) \
			> $(LOG_DIR)/backend.log 2>&1 & \
		echo $$! > $(PID_DIR)/backend.pid; \
		echo "✅ Backend 启动 (PID $$!, port $(BACKEND_PORT))"; \
	fi

# ── Dashboard 看板 ──
dashboard:
	@mkdir -p $(PID_DIR) $(LOG_DIR)
	@if [ -f $(PID_DIR)/dashboard.pid ] && kill -0 $$(cat $(PID_DIR)/dashboard.pid) 2>/dev/null; then \
		echo "⏭️  Dashboard 已在运行 (PID $$(cat $(PID_DIR)/dashboard.pid))"; \
	else \
		nohup python3 $(ROOT_DIR)/dashboard/server.py --port $(DASHBOARD_PORT) \
			> $(LOG_DIR)/dashboard.log 2>&1 & \
		echo $$! > $(PID_DIR)/dashboard.pid; \
		echo "✅ Dashboard 启动 (PID $$!, port $(DASHBOARD_PORT))"; \
	fi

# ── 数据刷新循环 ──
loop:
	@mkdir -p $(PID_DIR) $(LOG_DIR)
	@if [ -f $(PID_DIR)/loop.pid ] && kill -0 $$(cat $(PID_DIR)/loop.pid) 2>/dev/null; then \
		echo "⏭️  Loop 已在运行 (PID $$(cat $(PID_DIR)/loop.pid))"; \
	else \
		nohup bash $(ROOT_DIR)/scripts/run_loop.sh \
			> $(LOG_DIR)/loop.log 2>&1 & \
		echo $$! > $(PID_DIR)/loop.pid; \
		echo "✅ Loop 启动 (PID $$!)"; \
	fi

# ── 停止所有服务 ──
stop:
	@echo "🛑 停止服务..."
	@for svc in backend dashboard loop; do \
		if [ -f $(PID_DIR)/$$svc.pid ]; then \
			pid=$$(cat $(PID_DIR)/$$svc.pid); \
			if kill -0 $$pid 2>/dev/null; then \
				kill $$pid && echo "  ✅ $$svc (PID $$pid) 已停止"; \
			else \
				echo "  ⚪ $$svc (PID $$pid) 已不存在"; \
			fi; \
			rm -f $(PID_DIR)/$$svc.pid; \
		fi; \
	done

# ── 查看状态 ──
status:
	@for svc in backend dashboard loop; do \
		if [ -f $(PID_DIR)/$$svc.pid ] && kill -0 $$(cat $(PID_DIR)/$$svc.pid) 2>/dev/null; then \
			echo "🟢 $$svc (PID $$(cat $(PID_DIR)/$$svc.pid))"; \
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
