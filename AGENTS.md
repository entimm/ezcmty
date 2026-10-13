# AGENTS.md

## 项目

本项目是面向社区物业的消费返利与物业费抵扣平台。

主要技术栈：

- 管理后台：TypeScript、React、Ant Design、ProComponents
- 后端：Python、FastAPI
- 数据库：MySQL
- 居民端：微信小程序
- 运行组件：平台管理端、物业管理端、居民端、Webhook、任务系统

后端 Python 包根目录：`services/backend/src/backend_app/`。

后端 API 模块：

- `backend_app.api.platform_admin`
- `backend_app.api.property_admin`
- `backend_app.api.resident`
- `backend_app.api.webhook`

当前仓库目录名 `xlife2` 为临时名称，不得作为代码、包、服务或部署标识。

## 权威文档

- 开发规范：`docs/guidelines/development.md`
- 系统架构：`docs/architecture/overview.md`
- 部署约定：`docs/architecture/deployment.md`
- API 规范：`docs/api/conventions.md`
- OpenAPI 契约：`docs/api/openapi/`
- 数据库规范：`docs/database/conventions.md`

开始任务前，应阅读与当前任务相关的文档。详细规则以专题文档为准，本文件只保留长期执行要求。

## 执行要求

- 遵循 KISS、YAGNI、DRY，优先选择简单实现。
- 复杂任务先完成方案设计并等待审查，再开始实现。
- 遵循 OpenAPI First，先确定契约，再实现接口。
- 后端遵循 API → Service → Repository → Model 分层。
- 第三方能力统一放入 Integration。
- 数据库变更必须通过版本化迁移。
- 金额使用整数分，禁止浮点数。
- 密钥和敏感信息不得硬编码或提交。
- 日志不得泄露密码、Token 或其他敏感数据。
- 完成相关实现后，执行必要的格式、Lint、类型检查和测试。
- 未执行或未通过的验证不得声称已通过。
- 提交信息使用 Conventional Commits，描述使用中文。
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
