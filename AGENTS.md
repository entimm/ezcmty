# AGENTS.md

## 项目

本项目是面向社区物业的消费返利与物业费抵扣平台。

主要技术栈：

- 管理后台：TypeScript、React、Ant Design、ProComponents
- 后端：Python、FastAPI
- 数据库：MySQL
- 居民端：微信小程序
- 运行组件：平台管理端、物业管理端、居民端、Webhook、任务系统

## 权威文档

- 文档治理规范：[docs/standards/documentation.md](docs/standards/documentation.md)
- 开发规范：[docs/guidelines/development.md](docs/guidelines/development.md)
- 系统架构：[docs/architecture/overview.md](docs/architecture/overview.md)
- 部署约定：[docs/architecture/deployment.md](docs/architecture/deployment.md)
- API 规范：[docs/api/conventions.md](docs/api/conventions.md)
- OpenAPI 契约：[docs/api/openapi/](docs/api/openapi/)
- 数据库规范：[docs/database/conventions.md](docs/database/conventions.md)

开始任务前，应阅读并遵循与当前任务相关的权威文档。

## 执行要求

- 工程实现、安全、质量检查及提交遵循开发规范。
- API 设计与实现遵循 API 规范；数据与迁移遵循数据库规范。
- 文档新增、修改与审查遵循文档治理规范。
- 复杂任务先完成方案设计并等待审查，再开始实现。
- 只修改当前任务直接涉及的文件，不顺带重构无关代码。
- 当前任务完成后立即停止，不自行开始下一阶段。

## 自主决策与授权

可以自主决定：

- 局部函数、变量和文件命名。
- 局部算法和实现细节。
- 不影响公共契约和整体架构的小范围代码组织。

必须先获得授权：

- 修改整体架构或进程边界。
- 引入新的主要依赖或基础设施。
- 调整整体目录结构。
- 修改公共 API 或数据库结构。
- 删除、替换已有实现。
- 执行不可逆、破坏性或可能造成数据丢失的操作。
- 进行大规模重构。

发现当前任务之外的问题时，只记录建议，不擅自处理。
