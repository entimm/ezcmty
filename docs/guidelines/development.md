# 开发规范

## 范围

本文件记录稳定的工程约束。任务状态、执行记录和临时问题不写入长期文档。

## 代码组织

- 后端遵循 `API → Service → Repository → Model`。
- API 只负责 HTTP、输入校验、认证入口和响应转换。
- Service 负责业务规则、权限、数据范围、状态流转和事务边界。
- Repository 负责数据库访问。
- Integration 负责第三方协议和外部能力。
- 管理后台平台和物业功能共用项目，但保持独立路由、布局、会话和权限上下文。
- 后端平台、物业、居民和 Webhook 接口共用 Python 包，但使用独立进程运行。

## API 与数据库

- API 遵循 OpenAPI First。
- OpenAPI 契约位于 `docs/api/openapi/`，按业务模块拆分。
- 数据库结构变更必须通过版本化迁移。
- 金额以分为单位，禁止使用浮点数。
- 数据库访问必须经过 Repository。

## 安全

- 密钥、密码和令牌不得硬编码或提交。
- 敏感信息不得写入日志。
- 外部输入必须校验。
- 权限和数据范围必须由服务端执行。

## 质量检查

- Python 使用 Ruff、mypy 和 pytest。
- TypeScript 使用 ESLint、Prettier、TypeScript 和 Vitest。
- 修改完成后执行与改动相关的检查。
- 未执行或未通过的检查不得声称已通过。

## Git

提交信息使用 Conventional Commits：

```text
<type>(<scope>): <中文描述>
```

非简单改动使用独立分支或 worktree。无关问题只记录建议，不顺带处理。
