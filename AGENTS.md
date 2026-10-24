# AGENTS.md

## 项目

本项目是面向社区物业的消费返利与物业费抵扣平台。

主要技术栈：

- 管理后台：Ant Design Pro、Umi Max、TypeScript、React、Ant Design、ProComponents
- 后端：Python、FastAPI
- 数据库：PostgreSQL
- 居民端：微信小程序
- 运行组件：平台管理端、物业管理端、居民端、Webhook、任务系统

## 权威文档

- 文档治理规范：[docs/standards/documentation.md](docs/standards/documentation.md)
- 开发规范：[docs/guidelines/development.md](docs/guidelines/development.md)
- 后台前端开发规范：[docs/conventions/admin-frontend.md](docs/conventions/admin-frontend.md)
- 测试规范：[docs/conventions/testing.md](docs/conventions/testing.md)
- 系统架构：[docs/architecture/overview.md](docs/architecture/overview.md)
- 部署约定：[docs/architecture/deployment.md](docs/architecture/deployment.md)
- API 规范：[docs/api/conventions.md](docs/api/conventions.md)
- OpenAPI 契约：[openapi/](openapi/)
- 数据库规范：[docs/database/conventions.md](docs/database/conventions.md)

开始任务前，应阅读并遵循与当前任务相关的权威文档。

## 执行要求

- 工程实现、工程保障、安全、质量检查及提交遵循 [开发规范](docs/guidelines/development.md)。
- 后台前端新增、修改及评审遵循 [后台前端开发规范](docs/conventions/admin-frontend.md)，保持已确认的设计和双后台边界。
- 测试新增、维护与执行遵循测试规范。
- API 设计与实现遵循 API 规范；数据与迁移遵循数据库规范。
- 文档新增、修改与审查遵循文档治理规范。
- 复杂任务先完成方案设计；后续评审、确认、落盘及实施授权遵循 [设计工作流](docs/standards/documentation.md#设计工作流)。
- 工作量较大的任务，实施前须在 `docs/plans/` 对应主题目录编写并落盘可勾选的实施计划，明确任务拆分、依赖顺序和验收条件；执行中及时更新，仅在完成并验证后勾选。
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

涉及业务规则、授权边界、重大风险或不可逆操作的关键决策，若无法从现有需求和上下文确定，应提出必要问题，明确后再推进依赖该决策的工作。

发现当前任务之外的问题时，只记录建议，不擅自处理。

## 信息表达

需求讨论、方案说明、正式文档及交付报告均应以最低的阅读和理解成本，准确、完整地传递必要信息。

- 清晰易懂：用语准确、直白，避免冗长叙述和复杂句式。
- 简洁高效：使用短句、短段和必要的结构化表达，避免大段堆叠。
- 突出重点：结论先行，明确关键信息，必要时使用标题、列表或加粗强调。
- 完整准确：保留关键结论、必要依据、重要约束、风险及例外，不因追求简短而省略必要信息。
- 按需展开：简单问题直接回答；复杂问题分层组织，先呈现核心内容，再展开必要细节。
- 图文结合：根据内容选择合适的 Mermaid 图（如流程图、时序图、状态图等），配合文字说明。
