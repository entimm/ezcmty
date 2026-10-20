# 社区物业消费返利与物业费抵扣平台

本项目面向社区物业，提供消费返利、积分管理和物业费抵扣能力。

当前采用单仓库组织：

- `apps/admin-web/`：平台管理端和物业管理端共用的 Ant Design Pro 项目，工程与隔离设计见 [管理后台前端设计](docs/architecture/admin-web.md)。
- `apps/miniapp/`：居民微信小程序。
- `services/backend/`：共享 Python 后端包和独立运行进程。
- `docs/`：按主题组织的项目文档。

后端包、API 模块、进程职责及项目命名见 [系统架构](docs/architecture/overview.md)。

本地开发的环境准备、配置、命令、运行与质量检查见 [本地开发指南](docs/guidelines/local-development.md)。

测试环境的日常巡检、受控发布、迁移、证书维护和故障恢复见 [运维手册](docs/guidelines/staging-operations.md)。

账单支付的阶段依赖、可勾选任务及验收清单见 [开发实施计划](docs/plans/payment/bill-payments.md)。

执行要求及专题文档入口见 [AGENTS.md](AGENTS.md)。
