# 开发与部署约定

## 本地开发

- 默认复用本机已有 PostgreSQL 和 Redis；启动前由开发者确保实例已运行，并具备配置所需的数据库、账号和权限。
- 后端使用 `uv` 管理环境和进程。
- 管理后台使用 `pnpm` 和 Umi Max，工程设计见 [管理后台前端设计](admin-web.md)。
- 小程序使用微信开发者工具，TypeScript 源码先构建到 `dist/`。
- 依赖安装、配置优先级、启动停止、访问地址和质量检查操作集中维护在 [本地开发指南](../guidelines/local-development.md)。
- 开发入口的模块协作、批次与进程管理见 [本地开发入口设计](local-development.md)。

## 单机部署

推荐使用 Linux LTS 和 Nginx，应用及依赖直接运行于服务器：

- Nginx 提供管理后台 `dist/` 静态文件和后端 API 反向代理，前端路由回退到 `index.html`，API 代理独立处理；静态目录和上游地址由部署环境配置。
- 后端使用 `uv` 管理运行环境，五个后端运行组件分别由服务器进程管理器管理，支持独立重启。
- 生产发布包和源码分发排除 `services/backend/devtools/` 及 `.dev/`；开发数据工具的隔离要求见[开发数据填充设计](development-seed.md)。
- PostgreSQL 使用服务器持久化数据目录；部署环境维护数据库账号和权限，通过 `pg_dump` / `pg_restore` 备份与恢复并验证恢复可用性。
- Redis 的用途和会话丢失策略见 [系统架构](overview.md#会话)。
- 数据库迁移作为发布步骤执行，迁移约束见 [数据库规范](../database/conventions.md)。

## 配置

配置通过环境变量注入。变量名称使用通用名称，例如 `APP_NAME`、`APP_DATABASE_URL` 和 `APP_REDIS_URL`，命名约束见 [系统架构](overview.md#项目命名)。

真实密钥只存在于本地未提交环境文件或服务器受控配置中。
