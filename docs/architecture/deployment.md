# 开发与部署约定

## 本地开发

- 默认复用本机已有 MySQL 和 Redis；启动前由开发者确保实例已运行，并具备配置所需的数据库、账号和权限。
- Docker Compose 可作为依赖运行的可选方式，不是本地开发入口的必选前提。
- 后端使用 `uv` 管理环境和进程。
- 管理后台使用 `pnpm` 和 Vite。
- 小程序使用微信开发者工具，TypeScript 源码先构建到 `dist/`。
- 依赖安装、配置优先级、启动停止、访问地址和质量检查操作集中维护在 [本地开发指南](../guidelines/local-development.md)。

## 单机部署

推荐使用 Linux LTS、Docker Compose 和 Nginx：

- Nginx 提供静态文件和反向代理。
- 五个后端运行组件分别作为可独立重启的服务。
- MySQL 使用持久化卷，并由部署环境负责备份。
- Redis 的用途和会话丢失策略见 [系统架构](overview.md#会话)。
- 数据库迁移作为发布步骤执行，迁移约束见 [数据库规范](../database/conventions.md)。

## 配置

配置通过环境变量注入。变量名称使用通用名称，例如 `APP_NAME`、`APP_DATABASE_URL` 和 `APP_REDIS_URL`，命名约束见 [系统架构](overview.md#项目命名)。

真实密钥只存在于本地未提交环境文件或服务器受控配置中。
