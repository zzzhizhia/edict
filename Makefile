.PHONY: start stop status backend dashboard loop install

BACKEND_PORT ?= 8000
DASHBOARD_PORT ?= 17891
PID_DIR := .pids

# ── 一键启动所有服务 ──
start: $(PID_DIR)
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

$(PID_DIR):
	@mkdir -p $(PID_DIR)

# ── Backend API ──
backend: $(PID_DIR)
	@if [ -f $(PID_DIR)/backend.pid ] && kill -0 $$(cat $(PID_DIR)/backend.pid) 2>/dev/null; then \
		echo "⏭️  Backend 已在运行 (PID $$(cat $(PID_DIR)/backend.pid))"; \
	else \
		cd edict/backend && \
		nohup python3 -m uvicorn app.main:app --host 127.0.0.1 --port $(BACKEND_PORT) \
			> ../../logs/backend.log 2>&1 & \
		echo $$! > ../../$(PID_DIR)/backend.pid; \
		echo "✅ Backend 启动 (PID $$!, port $(BACKEND_PORT))"; \
	fi

# ── Dashboard 看板 ──
dashboard: $(PID_DIR)
	@if [ -f $(PID_DIR)/dashboard.pid ] && kill -0 $$(cat $(PID_DIR)/dashboard.pid) 2>/dev/null; then \
		echo "⏭️  Dashboard 已在运行 (PID $$(cat $(PID_DIR)/dashboard.pid))"; \
	else \
		nohup python3 dashboard/server.py --port $(DASHBOARD_PORT) \
			> logs/dashboard.log 2>&1 & \
		echo $$! > $(PID_DIR)/dashboard.pid; \
		echo "✅ Dashboard 启动 (PID $$!, port $(DASHBOARD_PORT))"; \
	fi

# ── 数据刷新循环 ──
loop: $(PID_DIR)
	@if [ -f $(PID_DIR)/loop.pid ] && kill -0 $$(cat $(PID_DIR)/loop.pid) 2>/dev/null; then \
		echo "⏭️  Loop 已在运行 (PID $$(cat $(PID_DIR)/loop.pid))"; \
	else \
		nohup bash scripts/run_loop.sh \
			> logs/loop.log 2>&1 & \
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

# ── 安装 ──
install:
	@mkdir -p logs
	bash install.sh
