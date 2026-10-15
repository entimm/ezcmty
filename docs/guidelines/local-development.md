# 本地开发指南

本指南维护本地开发操作。启动器的模块职责、批次归属、就绪判断和故障处理见 [本地开发入口设计](../architecture/local-development.md)。

## 开发环境

- Python 3.14.x（默认版本见 [.python-version](../../.python-version)，版本范围由 [后端项目配置](../../services/backend/pyproject.toml) 的 `requires-python` 声明）
- `uv`
- Node.js（默认使用 [.node-version](../../.node-version) 指定的 24.x，具体版本须满足 [package.json](../../package.json) 的 `engines.node`）
- `pnpm`
- PostgreSQL 18.x 和 Redis（默认复用本机已安装实例）
- 微信开发者工具

## 初始化本地环境

在仓库根目录执行：

```bash
make install
cp services/backend/.env.example services/backend/.env
```

`make install` 按现有锁文件安装后端开发依赖与整个 pnpm 工作区依赖。

[services/backend/.env.example](../../services/backend/.env.example) 是本地后端配置模板，仅包含 `APP_*`，默认连接本机 PostgreSQL 和 Redis。实际 `.env` 文件只在首次初始化时从对应模板复制，已有文件直接编辑。

启动前，使用你本机已有的管理方式启动 PostgreSQL 和 Redis，并确认已有数据库、账号及访问权限满足应用配置。开发入口仅检查已有配置与依赖；检查范围及处理方式见 [启动流程](../architecture/local-development.md#启动流程)。

编辑 `services/backend/.env`：

```dotenv
APP_DATABASE_URL=postgresql+psycopg://你的账号:你的密码@127.0.0.1:5432/已有数据库
APP_REDIS_URL=redis://127.0.0.1:6379/0
APP_LOG_LEVEL=INFO
```

URL 中的账号、密码须按 URL 规则编码。若 Redis 需要认证，配置对应凭据。模板中的数据库名和凭据仅为示例，需按本机已有实例填写。数据库须使用 UTF8 及确定性、大小写敏感的排序规则；PostgreSQL 18 可使用 builtin `C.UTF-8` locale。应用与迁移连接会显式设置 UTC，连接、语句及锁超时见 [数据库规范](../database/conventions.md#连接事务与查询)。

后端依赖检查及所有后端进程的工作目录固定为 `services/backend/`，沿用现有 Settings 读取该处 `.env`；**已有环境变量优先于 `.env`**。仓库根目录的 `.env` 不作为后端配置来源。包含 Worker 的启动批次需要 `APP_LOG_LEVEL=INFO` 或 `DEBUG`，以观察现有启动标记。配置及运行日志均不提交 Git。

管理后台使用 Umi 环境配置，可按需参考 [apps/admin-web/.env.example](../../apps/admin-web/.env.example) 配置该目录的本地环境文件。`UMI_APP_NAME` 配置公开应用名称，`UMI_APP_PLATFORM_API_BASE` 和 `UMI_APP_PROPERTY_API_BASE` 分别配置同源 API 前缀，默认是 `/api/platform`、`/api/property`；这些 `UMI_APP_*` 值会进入浏览器构建产物，不得包含密钥。开发代理将对应前缀转发到本机 8001、8002 并移除端入口前缀。单独启动管理后台无需 PostgreSQL、Redis 或后端配置。

## 开发命令

### 平台后台初始化

配置好已有 PostgreSQL 和 Redis 后，在仓库根目录执行数据库迁移，再进入后端目录执行受控初始化：

```bash
make migrate
cd services/backend
uv run python -m backend_app.cli init-platform-admin --login-name your-admin --display-name 平台管理员
```

登录名输入允许任意大小写，服务端统一为小写；公司和小区编码统一为大写，接口返回规范化后的形式。规范化与唯一性约束见 [数据库规范](../database/conventions.md#字符串与约束)。

初始化命令交互输入并确认密码，密码长度为 12–128 字符。已有有效超级管理员或同名账号时拒绝初始化，不能覆盖现有密码或授权。首次登录必须修改密码。

管理员会话空闲和绝对有效期分别由 `APP_ADMIN_SESSION_IDLE_SECONDS`、`APP_ADMIN_SESSION_ABSOLUTE_SECONDS` 配置；绝对有效期不能短于空闲有效期。`APP_ADMIN_TRUSTED_ORIGINS` 使用 JSON 数组，列出管理页面的完整 Origin；写请求必须来自其中之一。生产环境配置实际 HTTPS Origin，Cookie 会开启 Secure。

两端 Cookie 路径分别由 `APP_PLATFORM_ADMIN_COOKIE_PATH`、`APP_PROPERTY_ADMIN_COOKIE_PATH` 配置，必须与浏览器访问的 API 前缀一致且互不包含。登录尝试限制由 `APP_ADMIN_LOGIN_LIMIT` 和 `APP_ADMIN_LOGIN_WINDOW_SECONDS` 配置，按账号和来源 IP 分别执行。

平台与物业的域名和页面路径规则见 [域名与页面路径](../architecture/admin-web.md#域名与页面路径)。直接访问开发服务器时使用 `/platform`、`/property`；域名站点从 `/` 进入，未登录时跳转本端 `/login`。物业使用平台开通的公司管理员账号，公司和账号均须启用；首次登录要求改密，流程见 [物业管理端登录与基础工作台设计](../design/property/workbench.md)。

### 本地域名站点

将 `platform.xlife.test`、`property.xlife.test` 解析到 `127.0.0.1`，Nginx 在 8080 端口分别提供两个站点并转发到 `127.0.0.1:5173`。站点配置参考 [本地 Nginx 配置](../../apps/admin-web/config/nginx.local.conf)，Homebrew Nginx 可将其放入 `/opt/homebrew/etc/nginx/servers/xlife.test.conf`，执行 `nginx -t` 后重载。

访问地址为 `http://platform.xlife.test:8080/`、`http://property.xlife.test:8080/`。在 `services/backend/.env` 的 `APP_ADMIN_TRUSTED_ORIGINS` 中加入这两个完整 Origin，保留需要的直连开发 Origin；Cookie 路径使用对应 API 前缀。域名变更时同步配置前端 hostname 与后端可信 Origin。

若浏览器的代理规则使 `.test` 域名热更新 WebSocket 经 HTTP 代理发送 `CONNECT`，在 `apps/admin-web/.env.local` 配置 `SOCKET_SERVER=http://127.0.0.1:5173`，让本机热更新直接连接开发服务器；修改环境文件后重启管理后台。该配置仅用于本机开发。

### 服务命令

全部命令在仓库根目录执行；`make` 默认显示帮助。

| 命令                    | 用途                                                                 |
| ----------------------- | -------------------------------------------------------------------- |
| `make install`          | 安装后端及前端工作区开发依赖                                         |
| `make migrate`          | 执行 Alembic 数据库迁移，升级到 `head`                               |
| `make dev`              | 前台同时启动四个 API、Worker 和管理后台                              |
| `make dev-bg`           | 后台同时启动同样六个服务，全部就绪后返回                             |
| `make stop`             | 停止本仓库所有开发入口登记的批次                                     |
| `make platform`         | 前台启动平台管理 API，8001                                           |
| `make property`         | 前台启动物业管理 API，8002                                           |
| `make resident`         | 前台启动居民 API，8003                                               |
| `make webhook`          | 前台启动 Webhook，8004                                               |
| `make worker`           | 前台启动占位 Worker                                                  |
| `make admin`            | 前台启动管理后台，5173                                               |
| `make miniapp-build`    | 构建小程序到 `apps/miniapp/dist/`，通过微信开发者工具打开小程序项目  |
| `make check`            | 先运行根目录 Prettier，再依次运行后端、前端和 OpenAPI 检查           |
| `make check-backend`    | 后端源码、devtools、测试及仓库 scripts 的 Ruff、mypy、pytest         |
| `make check-frontend`   | 管理后台 typecheck、lint、test、build；小程序 typecheck、lint、build |
| `make check-api`        | 现有 `pnpm api:check`：OpenAPI lint、bundle、contract                |
| `make test-unit`        | 后端单元测试                                                         |
| `make test-integration` | 后端快速集成测试，排除专用 PostgreSQL/Redis 并发测试和进程生命周期   |
| `make test-contract`    | 后端与权威 OpenAPI 的契约一致性测试                                  |
| `make test-postgresql`  | 使用独立临时实例执行真实 PostgreSQL/Redis 测试                       |
| `make test-full`        | 全部后端和管理后台测试，包含真实依赖与进程生命周期，生成 JUnit 报告  |
| `make help`             | 显示全部命令及用途                                                   |

小程序不作为常驻进程；构建后使用微信开发者工具运行。

## 开发数据填充

seed 的场景、恢复与生产隔离规则见[开发数据填充设计](../architecture/development-seed.md)。工具只在源码检出中可用，所有业务数据通过现有 Service 写入。

先准备已迁移的开发 PostgreSQL 和 Redis，在 `services/backend/.env` 中显式配置 `APP_ENV=local`（隔离测试环境可以为 `test`）及 `SEED_ENABLED=1`。未配置环境、staging、production 或未启用开关时拒绝写入。已有环境变量仍优先于 `.env`。

```bash
make seed-list
make seed-plan SCENARIOS="property housing" SEED_ARGS="--set property.companies=3 --set housing.houses_per_unit=20"
make seed SCENARIOS="property housing" SEED_ARGS="--set property.companies=3 --set housing.houses_per_unit=20 --workers=2"
make seed                         # 默认全部场景；每次新增一批
make seed-resume RUN_ID=<批次标识> # 固定原批次参数续跑
make seed-coverage                # 只读核对实际数据库的表覆盖
```

`seed-plan` 和 `seed-list` 不连接数据库。写入前会打印数量估算，并检查迁移版本、表覆盖和 Redis。命令失败返回非零，保留已经提交的数据与上下文；重复执行 `seed` 是新批次，修复失败原因后应使用 `seed-resume` 完成原批次。

数量配置优先级为场景默认值、TOML 文件、`--set`。配置文件路径相对于 `services/backend/`；完整示例为 [example.toml](../../services/backend/devtools/seed/example.toml)：

```bash
make seed-plan SEED_ARGS="--config devtools/seed/example.toml"
make seed SEED_ARGS="--config devtools/seed/example.toml --set housing.houses_per_unit=50 --workers=2"
```

`SCENARIOS` 支持 `admin`、`property`、`housing`，多个名称用空格分隔；`all` 选择全部。仅选择 `housing` 时，默认准备一家物业、一个小区和一个物业管理员；可以覆盖其 `property.*` 前置参数。单独运行 `admin` 不生成物业数据。配置不得包含未选择且不属于依赖的场景。

| 场景     | 数量参数                | 默认值与范围                                                      |
| -------- | ----------------------- | ----------------------------------------------------------------- |
| admin    | accounts                | 新增平台演示账号 3 个，允许 0–100000；空库初始化执行账号另计      |
| admin    | roles                   | 新增自定义角色 2 个，允许 1–10000；系统角色另计                   |
| property | companies               | 新增物业公司 2 家，允许 1–10000                                   |
| property | communities_per_company | 每公司 2 个小区，允许 1–10000                                     |
| property | admins_per_company      | 每公司 3 个账号，允许 1–10000                                     |
| housing  | phases_per_community    | 每小区 1 个分期，允许 0–100                                       |
| housing  | buildings_per_community | 每小区总共 2 栋楼，允许 1–10000；有分期时交替覆盖根楼栋和分期楼栋 |
| housing  | units_per_building      | 每栋 2 个单元，允许 0–100                                         |
| housing  | houses_per_unit         | 每单元 3 套房，允许 0–100000                                      |
| housing  | houses_per_building     | 每栋直接挂载 1 套房，允许 0–100000，与单元房屋相加                |
| housing  | owners_per_house        | 每套房 2 条业主记录，允许 0–100                                   |

每组演示账号按顺序循环生成正常、待首次改密、停用账号；每家公司第一个账号保持可用于填充。多个角色时停用最后一个角色；多个小区或公司时在房屋填充完成后停用最后一个。房屋场景在创建子数据后停用末尾分期，以及存在多个同类记录时的末尾楼栋、单元、房屋和业主，以覆盖直接停用和祖先停用状态。数量少时不能覆盖所有状态；`report.json` 列出实际表记录、启停状态与未覆盖项目。

空库自动调用现有初始化 Service 建立开发执行账号，并完成首次改密。工具创建的执行账号凭据存储在 `.dev/seed/operator-<数据库指纹>.json`，后续批次复用。若数据库已有平台账号且没有工具凭据，配置已完成首次改密的平台超级管理员 `SEED_LOGIN_NAME` 和 `SEED_PASSWORD`；不要把密码放进命令参数或提交的配置。已有账号不会被重置。CLI 的会话与两类登录限流使用独立 Redis 键前缀，命名和隔离边界见[Redis 隔离](../architecture/development-seed.md#redis-隔离)。CLI 登录沿用账号与来源限流，来源按执行账号区分；触发限流时保留批次，等待窗口恢复或调整开发环境已有的登录限制后续跑。

每次运行输出 `.dev/seed/<run_id>/`。`accounts.md` 和 `accounts.json` 只包含所属批次、场景、登录端、登录名、显示名称、密码、所属物业公司七项；平台公司的值为空，登录端使用 `platform_admin`、`property_admin`。清单包含创建成功的正常、待改密和停用账号；密码为工具最后确认设置的值，人工改密后不会自动更新。失败时也导出已确认账号，未确认的改密结果需续跑核对后再使用。

`state.json` 保存参数和批次状态，`context.sqlite3` 增量保存步骤、结果及凭据。保存整个批次目录才能续跑，不手工编辑上下文。同一批次不能并发执行；数据库身份、迁移版本、场景版本或已生成数据发生不兼容变化时停止恢复。目录权限为 0700，文件为 0600，`.dev/` 不进入 Git。账号文件由受限上下文导出，普通日志不输出密码。

`--workers` 为并发填充房屋的公司数，默认 1，范围 1–8；同公司有序执行，物业接入顺序执行。所有操作保持 Service 原有事务与审计，参数按需生成，本地上下文逐步持久化；运行中约每 5 秒报告完成步骤与速度。生产数据库的持久化、网络延迟和数据规模会影响速度，测试环境的吞吐不能直接作为部署环境指标。

验证命令（在 `services/backend/` 执行，使用独立临时 PostgreSQL/Redis，不访问开发业务数据库）：

```bash
APP_RUN_POSTGRESQL_TESTS=1 uv run pytest tests/unit/seed tests/integration/postgresql/test_seed.py --require-all-tests
APP_RUN_POSTGRESQL_TESTS=1 uv run pytest tests/integration/postgresql/test_seed.py::test_thousand_houses_have_exact_counts_and_resume_without_growth --require-all-tests -s
```

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

测试分类、执行范围和结果判定遵循 [测试规范](../conventions/testing.md)。

```bash
make check
```

`make check-backend` 执行全部单元测试、快速集成测试和契约测试，通过 `postgresql`、`slow` 标记排除专用 PostgreSQL/Redis 并发测试与进程生命周期测试。`make check` 还执行前端测试及其余质量检查。

数据库和管理员接口集成测试使用独立临时 PostgreSQL 实例及每用例独立数据库，验证原生类型、迁移、真实提交、回滚和接口行为；快速集成测试同样需要 `initdb`、`postgres` 和 `pg_ctl` 在 PATH 中。合并前执行完整测试：

```bash
make test-full
```

完整测试需要本机可用的 `initdb`、`postgres`、`pg_ctl`、`redis-server` 以及已安装的前端依赖，会创建独立的临时实例、随机端口和测试数据库，完成后关闭并清理所属资源。JUnit 报告写入 `build/test-results/backend.xml` 和 `build/test-results/admin-web.xml`，CI 应保留这些报告和失败日志。

按模块、文件或用例运行时，在 `services/backend/` 下选择具体路径。例如：

```bash
uv run pytest tests/integration/api/property/test_onboarding.py --require-all-tests
uv run pytest tests/unit/core/test_admin_sessions.py::test_idle_session_expires --require-all-tests
APP_RUN_POSTGRESQL_TESTS=1 uv run pytest tests/integration/postgresql --require-all-tests
uv run pytest tests/integration/dev --require-all-tests --durations=20
```

测试分类和 `postgresql`、`slow` 标记按目录自动设置。直接运行 pytest 时，未启用 `APP_RUN_POSTGRESQL_TESTS=1` 的专用 PostgreSQL/Redis 测试会给出原因并跳过；显式启用后依赖缺失会失败。上述 Make 测试入口的后端检查均启用 `--require-all-tests`，选中测试出现跳过或预期失败时返回非零，未收集到测试沿用 pytest 的非零退出码。`make test-full` 还检查两端 JUnit 报告，拒绝空报告、跳过、失败及错误记录。

任一检查失败返回非零。也可使用上表中的单项检查或构建命令。

契约测试会调用现有 `pnpm api:bundle`，确保使用最新 OpenAPI 文件。API 设计与错误处理约定见 [API 规范](../api/conventions.md)。
