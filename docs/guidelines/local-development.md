# 本地开发指南

## 开发环境

- Python 3.12+
- `uv`
- Node.js 22+
- `pnpm`
- MySQL 8.x 和 Redis（默认复用本机已安装实例）
- 微信开发者工具

## 初始化本地环境

在仓库根目录执行：

```bash
make install
cp services/backend/.env.example services/backend/.env
```

后端支持 Python 3.12、3.13，Node.js 要求 22+；`make install` 按现有锁文件安装后端开发依赖与整个 pnpm 工作区依赖。

[services/backend/.env.example](../../services/backend/.env.example) 是本地后端配置模板，仅包含 `APP_*`，默认连接本机 MySQL 和 Redis。实际 `.env` 文件只在首次初始化时从对应模板复制，已有文件直接编辑。

启动前，使用你本机已有的管理方式启动 MySQL 和 Redis，并确认已有数据库、账号及访问权限满足应用配置。开发入口只做连接、`SELECT 1` 和 Redis `PING` 检查，不启停系统服务、不建库或创建账号、不执行迁移、不修改已有数据。

编辑 `services/backend/.env`：

```dotenv
APP_DATABASE_URL=mysql+pymysql://你的账号:你的密码@127.0.0.1:3306/已有数据库?charset=utf8mb4
APP_REDIS_URL=redis://127.0.0.1:6379/0
APP_LOG_LEVEL=INFO
```

URL 中的账号、密码须按 URL 规则编码。若 Redis 需要认证，配置对应凭据。模板中的数据库名和凭据仅为示例，需按本机已有实例填写。

后端依赖检查及所有后端进程的工作目录固定为 `services/backend/`，沿用现有 Settings 读取该处 `.env`；**已有环境变量优先于 `.env`**。仓库根目录的 `.env` 不作为后端配置来源。包含 Worker 的启动批次需要 `APP_LOG_LEVEL=INFO` 或 `DEBUG`，以观察现有启动标记。配置及运行日志均不提交 Git。

管理后台沿用 Vite 配置机制，可按需参考 `apps/admin-web/.env.example` 配置该目录的本地环境文件。单独启动管理后台无需 MySQL、Redis 或后端配置。

## 开发命令

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

日志标明所属服务，全部服务就绪后显示地址。四个 API 默认开启 Uvicorn 热重载，监听 `services/backend/src/`；管理后台沿用 Vite 热更新和严格端口模式。所有服务仅监听本机 `127.0.0.1`。

| 服务         | 访问地址                                                            |
| ------------ | ------------------------------------------------------------------- |
| 平台管理 API | http://127.0.0.1:8001/docs                                          |
| 物业管理 API | http://127.0.0.1:8002/docs                                          |
| 居民 API     | http://127.0.0.1:8003/docs                                          |
| Webhook      | http://127.0.0.1:8004/docs                                          |
| 平台管理页面 | http://127.0.0.1:5173/platform                                      |
| 物业管理页面 | http://127.0.0.1:5173/property                                      |
| Worker       | 无 HTTP 入口；当前为 `task_handlers=0` 的占位进程，尚无任务处理能力 |

API 就绪依据各自 `/readyz` 的 HTTP 200、服务标识以及 MySQL、Redis 的 `ok` 状态；Worker 依据启动前只读依赖检查、本次 `worker_started task_handlers=0` 标记与实际进程存活；管理后台依据 HTTP 页面可访问。进程存活或端口监听本身不足以报告启动成功。

后台运行：

```bash
make dev-bg
```

后台协调器与服务脱离当前终端，关闭终端后继续运行。全部服务就绪后，命令显示批次、地址、日志目录与停止命令。前后台使用相同的协调、就绪及故障清理逻辑。

每批日志位于 `.dev/run/<批次 ID>/`：`platform.log`、`property.log`、`resident.log`、`webhook.log`、`worker.log`、`admin.log`，以及记录启动、重载、失败和停止原因的 `coordinator.log`。该目录的 `state.json` 保留批次最终状态，仓库活动登记位于 `.dev/run/state.json`。整个 `.dev/` 已加入 Git 和 Prettier 忽略规则。

启动总超时为 **60 秒**，包含后端依赖检查与全部所选服务就绪；单次探测最多 **10 秒**，探测和进程检查间隔为 **0.5 秒**。未通过的探测在总期限内重试，确定的配置错误或进程退出直接失败。正常热重载允许旧子进程被替换，新进程须在 **20 秒**内重新就绪；连续变更不会无限延长恢复期限。

## 停止与启动冲突

前台的 `Ctrl+C` 只停止本次启动的批次，包括热重载子进程；也可从另一个终端停止所有登记批次：

```bash
make stop
```

停止先请求正常退出，等待最多 **10 秒**，随后终止仍存活的所属进程，再等待最多 **5 秒**。每次发信号前验证 PID、进程组和精确启动时间，清理子进程与过期登记。没有运行服务或重复停止时正常返回。

每次启动都是独立批次。请求中的任一服务已经运行或正在启动时，整条请求拒绝并返回非零，显示已有实例及停止方式，不补启动其余服务。例如先运行 `make platform`，再运行 `make dev-bg`，后者会拒绝且原平台 API 继续运行。不同服务可分别启动；`make stop` 会停止所有批次。启停通过仓库锁协调，停止期间的新启动请求会被拒绝。

端口被其他进程占用时明确报错，不终止占用者或自动换端口。任一服务启动失败、超时或意外退出（包括意外零退出码），只清理同批进程，保留其他独立批次。API 监控实际子进程，重载父进程存活不会掩盖子进程故障。后台发生故障时，查看对应批次的 `coordinator.log` 和 `state.json`。

## 质量检查

```bash
make check
```

任一检查失败返回非零。也可使用上表中的单项检查或构建命令。

契约测试会调用现有 `pnpm api:bundle`，确保使用最新 OpenAPI 文件。API 设计与错误处理约定见 [API 规范](../api/conventions.md)。
