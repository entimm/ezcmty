# 开发规范

## 范围

本文件维护工程原则、安全、质量检查和 Git 约定。文档维护遵循 [长期文档治理规范](../standards/documentation.md)。

## 工程原则

遵循 KISS、YAGNI、DRY，优先选择简单实现。

## 工程保障

- 代理应根据任务实际需要和风险，在已授权范围内主动设计、实现并验证并发控制、幂等性、权限校验、数据一致性、重复扣款防护、异常恢复等必要工程保障，无需用户提醒。
- 常规需求讨论无需逐项说明或单独确认上述保障。关键决策的澄清和授权要求遵循 [自主决策与授权](../../AGENTS.md#自主决策与授权)，不得以工程保障为由扩大任务或授权范围。
- 正式文档的记录要求遵循 [工程保障的文档要求](../standards/documentation.md#工程保障的文档要求)。
- 交付时简要说明关键保障措施、实际验证结果及遗留风险；未完成的验证和保障限制应明确说明。

## 专题约定

- 本地环境准备、配置、运行和检查命令见 [本地开发指南](local-development.md)。
- 测试分类、组织、隔离与执行要求见 [测试规范](../conventions/testing.md)。
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
