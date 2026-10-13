# 社区物业消费返利与物业费抵扣平台

本项目面向社区物业，提供消费返利、积分管理和物业费抵扣能力。

当前采用单仓库组织：

- `apps/admin-web/`：平台管理端和物业管理端共用的 React 项目。
- `apps/miniapp/`：居民微信小程序。
- `services/backend/`：共享 Python 后端包和独立运行进程。
- `docs/`：项目规范、架构、API、数据库和模块文档。
- `deploy/`：本地和服务器部署模板。

后端进程：

- `platform-admin-api`
- `property-admin-api`
- `resident-api`
- `webhook`
- `worker`

后端包的稳定 Python 命名空间为 `backend_app`。本地仓库目录 `xlife2` 是临时名称，不参与代码、包或部署命名。

## 开发环境

- Python 3.12+
- `uv`
- Node.js 22+
- `pnpm`
- Docker Compose
- 微信开发者工具

## 初始化本地环境

```bash
cp deploy/env/.env.example services/backend/.env
docker compose -f deploy/compose/docker-compose.yml up -d mysql redis
uv sync --project services/backend --extra dev
pnpm install
```

启动一个后端进程示例：

```bash
cd services/backend
uv run uvicorn backend_app.runtimes.platform_admin_api:app --reload --port 8001
```

管理后台：

```bash
pnpm --filter admin-web dev
```

OpenAPI 校验和构建：

```bash
pnpm api:check
```

后端质量检查从 `services/backend/` 目录执行：

```bash
cd services/backend
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
uv run pytest
```

详细规则请阅读 `AGENTS.md` 及 `docs/` 下的专题文档。
