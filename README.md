# 社区物业消费返利与物业费抵扣平台

本项目面向社区物业，提供消费返利、积分管理和物业费抵扣能力。

当前采用单仓库组织：

- `apps/admin-web/`：平台管理端和物业管理端共用的 React 项目。
- `apps/miniapp/`：居民微信小程序。
- `services/backend/`：共享 Python 后端包和独立运行进程。
- `docs/`：按主题组织的项目文档。

后端包、API 模块、进程职责及项目命名见 [系统架构](docs/architecture/overview.md)。

本地开发的环境准备、配置、命令、运行与质量检查见 [本地开发指南](docs/guidelines/local-development.md)。

执行要求及专题文档入口见 [AGENTS.md](AGENTS.md)。
