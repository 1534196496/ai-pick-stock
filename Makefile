SHELL := /bin/sh

COMPOSE_V2 := docker compose -f compose.v2.yaml

.DEFAULT_GOAL := help

.PHONY: help bootstrap dev down lint typecheck test build e2e openapi-check

help: ## 显示可用命令
	@printf '%s\n' \
		'make bootstrap  安装 API 与 Web 依赖' \
		'make dev        启动 V2 Web、API、Worker 与 PostgreSQL' \
		'make down       停止 V2 本地服务' \
		'make lint       检查 API 与 Web 代码风格' \
		'make typecheck  检查 Python 与 TypeScript 类型' \
		'make test       运行 API 与 Web 测试和覆盖率门禁' \
		'make build      构建 V2 容器镜像' \
		'make e2e        运行浏览器端到端测试' \
		'make openapi-check  检查 API 与前端 Client 契约漂移'

bootstrap: ## 安装开发依赖
	cd apps/api && uv sync --all-groups
	cd apps/web && npm ci

dev: ## 启动 V2 开发环境
	$(COMPOSE_V2) up --build

down: ## 停止 V2 开发环境
	$(COMPOSE_V2) down

lint: ## 运行代码风格检查
	cd apps/api && uv run ruff check .
	cd apps/web && npm run lint

typecheck: ## 运行静态类型检查
	cd apps/api && uv run mypy app
	cd apps/web && npm run typecheck

test: ## 运行测试和覆盖率门禁
	cd apps/api && uv run pytest --cov=app --cov-report=term-missing --cov-fail-under=80
	cd apps/web && npm run test -- --coverage

build: ## 构建 V2 镜像
	$(COMPOSE_V2) build

e2e: ## 运行端到端测试
	cd apps/web && npm run e2e

openapi-check: ## 检查 OpenAPI 与前端生成类型无漂移
	cd apps/api && uv run python -m scripts.generate_openapi
	./scripts/check_openapi_client.sh
