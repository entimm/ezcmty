.DEFAULT_GOAL := help

DEV := uv run --project services/backend --no-sync python -m scripts.dev
BACKEND := cd services/backend && uv run --no-sync
POSTGRESQL_TEST := cd services/backend && APP_RUN_POSTGRESQL_TESTS=1 uv run --no-sync pytest --require-all-tests

.PHONY: install migrate dev dev-bg stop platform property resident webhook worker admin miniapp-build check check-backend check-frontend check-api test-unit test-integration test-contract test-postgresql test-full help

install: ## 安装前后端开发依赖
	@printf '\n[安装] 后端开发依赖\n'
	uv sync --project services/backend --extra dev --locked
	@printf '\n[安装] 前端工作区依赖\n'
	pnpm install --frozen-lockfile
	@printf '\n[完成] 依赖已安装；配置方式见 docs/guidelines/local-development.md\n'

migrate: ## 执行数据库迁移到最新版本（Alembic head）
	@printf '\n[迁移] 升级数据库到最新版本\n'
	$(BACKEND) alembic upgrade head

dev: ## 前台启动四个 API、Worker 和管理后台
	@$(DEV) start all

dev-bg: ## 后台启动全部应用服务，等待全部就绪
	@$(DEV) start all --background

stop: ## 停止本仓库开发入口登记的所有应用进程
	@$(DEV) stop

platform: ## 前台启动平台管理 API（8001）
	@$(DEV) start platform

property: ## 前台启动物业管理 API（8002）
	@$(DEV) start property

resident: ## 前台启动居民 API（8003）
	@$(DEV) start resident

webhook: ## 前台启动 Webhook（8004）
	@$(DEV) start webhook

worker: ## 前台启动占位 Worker（task_handlers=0）
	@$(DEV) start worker

admin: ## 前台启动管理后台（5173，严格端口模式）
	@$(DEV) start admin

miniapp-build: ## 构建居民小程序到 apps/miniapp/dist
	@printf '\n[构建] 居民小程序\n'
	pnpm --filter resident-miniapp build

check: ## 顺序执行 Prettier 和全部质量检查
	@printf '\n[检查] 仓库 Prettier\n'
	pnpm format:check
	@$(MAKE) check-backend
	@$(MAKE) check-frontend
	@$(MAKE) check-api
	@printf '\n[完成] 默认质量检查通过\n'

check-backend: ## 后端及仓库 scripts：Ruff、mypy、pytest
	@printf '\n[检查] 后端与仓库 scripts\n'
	$(BACKEND) ruff check --config pyproject.toml src tests ../../scripts
	$(BACKEND) ruff format --config pyproject.toml --check src tests ../../scripts
	$(BACKEND) mypy
	$(BACKEND) pytest -m "not postgresql and not slow" --require-all-tests

test-unit: ## 后端单元测试
	$(BACKEND) pytest tests/unit --require-all-tests

test-integration: ## 后端集成测试（排除专用 PostgreSQL/Redis 并发测试和进程生命周期）
	$(BACKEND) pytest tests/integration -m "not postgresql and not slow" --require-all-tests

test-contract: ## 后端与权威 OpenAPI 的契约一致性测试
	$(BACKEND) pytest tests/contract --require-all-tests

test-postgresql: ## 隔离 PostgreSQL/Redis 集成测试（依赖缺失时失败）
	$(POSTGRESQL_TEST) tests/integration/postgresql

test-full: ## 全部后端及管理后台测试，生成 JUnit 报告
	$(POSTGRESQL_TEST) --junitxml=../../build/test-results/backend.xml
	pnpm --filter admin-web test --reporter=default --reporter=junit --outputFile=../../build/test-results/admin-web.xml
	uv run --project services/backend --no-sync python -m scripts.check_test_results build/test-results/backend.xml build/test-results/admin-web.xml

check-frontend: ## 管理后台与小程序：类型、Lint、测试及构建
	@printf '\n[检查] 管理后台\n'
	pnpm --filter admin-web typecheck
	pnpm --filter admin-web lint
	pnpm --filter admin-web test
	pnpm --filter admin-web build
	@printf '\n[检查] 居民小程序\n'
	pnpm --filter resident-miniapp typecheck
	pnpm --filter resident-miniapp lint
	pnpm --filter resident-miniapp build

check-api: ## OpenAPI lint、bundle、contract
	@printf '\n[检查] OpenAPI 契约\n'
	pnpm api:check

help: ## 显示全部命令及用途
	@printf '本地开发命令（在仓库根目录执行）\n\n'
	@awk 'BEGIN { FS = ":.*## " } /^[a-z][a-z-]*:.*## / { printf "  make %-17s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
