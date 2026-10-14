# 本地开发指南

本指南维护本地开发操作。启动器的模块职责、批次归属、就绪判断和故障处理见 [本地开发入口设计](../architecture/local-development.md)。

## 开发环境

- Python 3.12+
- `uv`
- Node.js（默认使用 [.node-version](../../.node-version) 指定的 24.x，具体版本须满足 [package.json](../../package.json) 的 `engines.node`）
- `pnpm`
- MySQL 8.x 和 Redis（默认复用本机已安装实例）
- 微信开发者工具

## 初始化本地环境

在仓库根目录执行：

```bash
make install
cp services/backend/.env.example services/backend/.env
```

后端支持 Python 3.12、3.13；`make install` 按现有锁文件安装后端开发依赖与整个 pnpm 工作区依赖。

[services/backend/.env.example](../../services/backend/.env.example) 是本地后端配置模板，仅包含 `APP_*`，默认连接本机 MySQL 和 Redis。实际 `.env` 文件只在首次初始化时从对应模板复制，已有文件直接编辑。

启动前，使用你本机已有的管理方式启动 MySQL 和 Redis，并确认已有数据库、账号及访问权限满足应用配置。开发入口仅检查已有配置与依赖；检查范围及处理方式见 [启动流程](../architecture/local-development.md#启动流程)。

编辑 `services/backend/.env`：

```dotenv
APP_DATABASE_URL=mysql+pymysql://你的账号:你的密码@127.0.0.1:3306/已有数据库?charset=utf8mb4
APP_REDIS_URL=redis://127.0.0.1:6379/0
APP_LOG_LEVEL=INFO
```

URL 中的账号、密码须按 URL 规则编码。若 Redis 需要认证，配置对应凭据。模板中的数据库名和凭据仅为示例，需按本机已有实例填写。

后端依赖检查及所有后端进程的工作目录固定为 `services/backend/`，沿用现有 Settings 读取该处 `.env`；**已有环境变量优先于 `.env`**。仓库根目录的 `.env` 不作为后端配置来源。包含 Worker 的启动批次需要 `APP_LOG_LEVEL=INFO` 或 `DEBUG`，以观察现有启动标记。配置及运行日志均不提交 Git。

管理后台使用 Umi 环境配置，可按需参考 [apps/admin-web/.env.example](../../apps/admin-web/.env.example) 配置该目录的本地环境文件。`UMI_APP_NAME` 配置公开应用名称，`UMI_APP_PLATFORM_API_BASE` 和 `UMI_APP_PROPERTY_API_BASE` 分别配置同源 API 前缀，默认是 `/api/platform`、`/api/property`；这些 `UMI_APP_*` 值会进入浏览器构建产物，不得包含密钥。开发代理将对应前缀转发到本机 8001、8002 并移除端入口前缀。单独启动管理后台无需 MySQL、Redis 或后端配置。

## 开发命令

### 平台后台初始化

配置好已有 MySQL 和 Redis 后，在 `services/backend/` 下执行数据库迁移和受控初始化：

```bash
uv run alembic upgrade head
uv run python -m backend_app.cli init-platform-admin --login-name your-admin --display-name 平台管理员
```

初始化命令交互输入并确认密码，密码长度为 12–128 字符。已有有效超级管理员或同名账号时拒绝初始化，不能覆盖现有密码或授权。首次登录必须修改密码。

管理员会话空闲和绝对有效期分别由 `APP_ADMIN_SESSION_IDLE_SECONDS`、`APP_ADMIN_SESSION_ABSOLUTE_SECONDS` 配置；绝对有效期不能短于空闲有效期。`APP_ADMIN_TRUSTED_ORIGINS` 使用 JSON 数组，列出管理页面的完整 Origin；写请求必须来自其中之一。生产环境配置实际 HTTPS Origin，Cookie 会开启 Secure。

两端 Cookie 路径分别由 `APP_PLATFORM_ADMIN_COOKIE_PATH`、`APP_PROPERTY_ADMIN_COOKIE_PATH` 配置，必须与浏览器访问的 API 前缀一致且互不包含。登录尝试限制由 `APP_ADMIN_LOGIN_LIMIT` 和 `APP_ADMIN_LOGIN_WINDOW_SECONDS` 配置，按账号和来源 IP 分别执行。

平台后台访问 `/platform`，未登录时进入登录页面。物业登录启用前提见 [管理后台基础框架设计](../design/admin/foundation.md#范围与职责)。

### 服务命令

全部命令在仓库根目录执行；`make` 默认显示帮助。

| 命令                  | 用途                                                                  |
| --------------------- | --------------------------------------------------------------------- |
| `make install`        | 安装后端及前端工作区开发依赖                                          |
| `make dev`            | 前台同时启动四个 API、Worker 和管理后台                               |
| `make dev-bg`         | 后台同时启动同样六个服务，全部就绪后返回                              |
| `make stop`           | 停止本仓库所有开发入口登记的批次                                      |
| `make platform`       | 前台启动平台管理 API，8001                                            |
| `make property`       | 前台启动物业管理 API，8002                                            |
| `make resident`       | 前台启动居民 API，8003                                                |
| `make webhook`        | 前台启动 Webhook，8004                                                |
| `make worker`         | 前台启动占位 Worker                                                   |
| `make admin`          | 前台启动管理后台，5173                                                |
| `make miniapp-build`  | 构建小程序到 `apps/miniapp/dist/`，通过微信开发者工具打开小程序项目   |
| `make check`          | 先运行根目录 Prettier，再依次运行后端、前端和 OpenAPI 检查            |
| `make check-backend`  | 后端源码、测试及仓库 scripts 的 Ruff lint、format check、mypy、pytest |
| `make check-frontend` | 管理后台 typecheck、lint、test、build；小程序 typecheck、lint、build  |
| `make check-api`      | 现有 `pnpm api:check`：OpenAPI lint、bundle、contract                 |
| `make help`           | 显示全部命令及用途                                                    |

小程序不作为常驻进程；构建后使用微信开发者工具运行。

## 运行、地址与日志

前台运行：

```bash
make dev
```

日志标明所属服务，全部服务就绪后显示地址。四个 API 默认开启 Uvicorn 热重载，监听 `services/backend/src/`；管理后台使用 Umi 热更新，开发端口固定且不自动切换。所有服务仅监听本机 `127.0.0.1`。

| 服务         | 访问地址                                                            |
| ------------ | ------------------------------------------------------------------- |
| 平台管理 API | http://127.0.0.1:8001/docs                                          |
| 物业管理 API | http://127.0.0.1:8002/docs                                          |
| 居民 API     | http://127.0.0.1:8003/docs                                          |
| Webhook      | http://127.0.0.1:8004/docs                                          |
| 平台管理页面 | http://127.0.0.1:5173/platform                                      |
| 物业管理页面 | http://127.0.0.1:5173/property                                      |
| Worker       | 无 HTTP 入口；当前为 `task_handlers=0` 的占位进程，尚无任务处理能力 |

启动入口会等待全部所选服务通过各自的 [就绪判断](../architecture/local-development.md#就绪判断)，再报告启动成功。

后台运行：

```bash
make dev-bg
```

后台协调器与服务脱离当前终端，关闭终端后继续运行。全部服务就绪后，命令显示批次、地址、日志目录与停止命令。前后台使用相同的协调、就绪及故障清理逻辑。

每批日志位于 `.dev/run/<批次 ID>/`：`platform.log`、`property.log`、`resident.log`、`webhook.log`、`worker.log`、`admin.log`，以及记录启动、重载、失败和停止原因的 `coordinator.log`。该目录的 `state.json` 保留批次最终状态，仓库活动登记位于 `.dev/run/state.json`。整个 `.dev/` 已加入 Git 和 Prettier 忽略规则。

启动、单次探测、热重载恢复和停止的默认时限见 [时间限制](../architecture/local-development.md#时间限制)。正常热重载及实际 API 子进程故障的识别方式见 [API 热重载与故障识别](../architecture/local-development.md#api-热重载与故障识别)。

## 停止与启动冲突

前台的 `Ctrl+C` 只停止本次启动的批次，包括热重载子进程；也可从另一个终端停止所有登记批次：

```bash
make stop
```

停止命令会请求正常退出并清理所属子进程，没有运行服务或重复停止时正常返回。身份校验、超时终止和过期登记的处理见 [停止与故障清理](../architecture/local-development.md#停止与故障清理)。

每次启动都是独立批次。例如先运行 `make platform`，再运行 `make dev-bg`，后者会拒绝且原平台 API 继续运行。不同服务可分别启动；`make stop` 会停止所有批次。完整的冲突与并发启停规则见 [批次登记与并发控制](../architecture/local-development.md#批次登记与并发控制)。

端口冲突时，按错误提示自行处理占用者后重新启动。后台发生故障时，查看对应批次的 `coordinator.log` 和 `state.json`；批次清理机制见 [停止与故障清理](../architecture/local-development.md#停止与故障清理)。

## 质量检查

```bash
make check
```

管理员接口回归使用临时 SQLite 数据库验证迁移、事务和接口行为。MySQL 行锁与真实 Redis 的集成检查在 `services/backend/` 下执行：

```bash
APP_RUN_MYSQL_TESTS=1 uv run pytest tests/integration
```

该检查需要本机可用的 `mysqld` 和 `redis-server`，会创建独立的临时实例、随机端口和测试数据库，完成后关闭并清理测试资源。

任一检查失败返回非零。也可使用上表中的单项检查或构建命令。

契约测试会调用现有 `pnpm api:bundle`，确保使用最新 OpenAPI 文件。API 设计与错误处理约定见 [API 规范](../api/conventions.md)。
