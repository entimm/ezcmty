# 开发规范

## 范围

本文件维护工程原则、安全、质量检查和 Git 约定。文档维护遵循 [长期文档治理规范](../standards/documentation.md)。

## 工程原则

遵循 KISS、YAGNI、DRY，优先选择简单实现。

## 专题约定

- 代码组织与进程边界见 [系统架构](../architecture/overview.md)。
- API 设计与契约维护见 [API 规范](../api/conventions.md)。
- 数据库与迁移见 [数据库规范](../database/conventions.md)。

## 安全

- 密钥、密码和令牌不得硬编码或提交。
- 敏感信息不得写入日志。
- 外部输入必须校验。
- 权限和数据范围必须由服务端执行。

## 质量检查

- Python 使用 Ruff、mypy 和 pytest。
- TypeScript 使用 ESLint、Prettier、TypeScript 和 Vitest。
- 修改完成后执行与改动相关的必要格式、Lint、类型检查和测试。
- 未执行或未通过的检查不得声称已通过。

## Git

提交信息使用 Conventional Commits：

```text
<type>(<scope>): <中文描述>
```

非简单改动使用独立分支或 worktree。任务范围控制遵循 [AGENTS.md](../../AGENTS.md#执行要求)。
