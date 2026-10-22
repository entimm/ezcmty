# 通用批量导入验收记录

## 交付范围

2026-10-23，在独立 worktree `.worktrees/imports`、分支 `feat/generic-imports` 完成 [实施计划](implementation.md) 的代码及专项验收。P7-05 的全仓质量门禁仍受下述既有格式问题阻断，未勾选为完成。

已实现八表及迁移、持久请求幂等、私有文件与有界解析、版本注册、持久 Worker、预检确认、执行账本、取消、原任务恢复、失败新批次、错误文件、保留清理，以及平台与物业两端 API 和管理页面。正式 OpenAPI 版本为 `0.14.0`。

生产注册表保持为空。完整流程仅使用测试适配器、隔离 PostgreSQL、独立文件目录和测试进程。未加入业务导入类型、业务模板、业务适配器或业务列表入口；未部署，未操作真实业务数据，未提交、合并或推送 Git。

## 检查结果

命令默认在 worktree 根目录执行；Python 工具在 `services/backend/` 执行。

| 检查                                          | 实际结果                                                                                                                 |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `make test-full`                              | 通过。后端 848、管理后台 194、小程序 66，共 1108 项；无失败、错误或跳过。覆盖真实 PostgreSQL、Redis、迁移和进程测试。    |
| 最终导入回归                                  | 38 项通过，无失败或跳过。覆盖最终 API、处理链、进程与上传边界修改。与完整测试存在重叠，不另计独立总数。                  |
| 真实 SQL 执行计划专项                         | 1 项通过，无失败或跳过。20 家公司、8000 批次、50,000 行、8000 任务，`ANALYZE` 后保持顺序扫描开启，实际查询选中预期索引。 |
| Ruff、Ruff format、mypy                       | 全部通过，覆盖最终 419 个 Python 文件及项目脚本。                                                                        |
| `make check-frontend`                         | 两端 TypeScript、ESLint、Vitest、边界检查及生产构建通过。                                                                |
| `pnpm api:check`                              | OpenAPI lint、bundle、错误目录生成一致性及四运行端契约检查通过。                                                         |
| 本任务修改文件的 Prettier、`git diff --check` | 通过。                                                                                                                   |
| `make check`                                  | 未通过。唯一已知阻塞为下述未修改文件的既有格式问题。                                                                     |

最终导入回归命令：

```sh
APP_RUN_POSTGRESQL_TESTS=1 .venv/bin/pytest \
  tests/integration/api/platform/imports \
  tests/integration/api/property/imports \
  tests/integration/postgresql/imports/test_pipeline.py \
  tests/integration/runtime/import_tasks/test_processes.py \
  tests/unit/api/test_import_upload.py \
  --require-all-tests --junitxml=../../build/test-results/imports-final.xml
```

执行计划专项命令：

```sh
APP_RUN_POSTGRESQL_TESTS=1 .venv/bin/pytest \
  tests/integration/postgresql/imports/test_query_plans.py \
  --require-all-tests --junitxml=../../build/test-results/imports-query-plans.xml
```

本地 JUnit 报告保存在 `build/test-results/`：`backend.xml`、`admin-web.xml`、`miniapp.xml`、`imports-final.xml` 和 `imports-query-plans.xml`。报告由项目结果检查器验证非空且无失败、错误、跳过，属于忽略的构建产物，不进入源码。

## 关键验收证据

- 数据库：空库迁移、八表原生约束、同键重放与异输入冲突、真实会话并发确认、操作键竞争、取消与提交争用、租约代次保护及成功账本不可变。
- 处理链：上传至预检、显式确认、执行、错误文件、失败新批次、再次确认的真实 HTTP 与 Worker 流程；原批次历史保持不变。未知提交按原键核实，保留期后恢复不再新建业务对象。
- 文件：真实 CSV/XLSX、UTF-8 多字节与跨行恢复、公式与宏及外链拒绝、10 MiB 上传和 100 MiB 解压限制、私有权限、磁盘故障、分片发布和下载白名单。原键上传重放在文件已清理后仍返回首次安全响应。
- 容量：50,000 行 CSV 分 100 个 500 行块解析，解析分配峰值低于 16 MiB；XLSX 验证 50,000 行、200 列边界及 1500 行分块恢复，解析分配峰值低于 32 MiB。该指标为解析器分配内存，不作为部署进程 RSS 保证。
- 调度：真实 50,000 行 Worker 解析分 250 个 200 行块执行；25 个支付任务每 10 块到达后在下一轮领取。验证 3 秒租约、独立心跳、崩溃退出后接管与 SIGTERM 安全 checkpoint。
- 保留清理：真实 PostgreSQL 验证活动及暂停任务、未知结果和共享操作保护，30 天敏感输入清理、24 小时草稿失效、删除失败重试和孤儿扫描保护。
- 安装制品：独立 wheel 安装后从包资源读取版本配置；测试旧版本恢复和缺失、漂移阻断。生产 wheel 无业务类型及测试适配器。
- 前端与权限：两端范围隔离、CSRF、权限失效、会话切换清理、空目录、行定位、显式执行策略、未知响应原键核实和旧历史展示。

## 遗留问题与停止边界

全仓 `make check` 在 Prettier 阶段因 `deploy/staging/README.md` 失败。该文件与任务开始时的 HEAD 完全一致，`git diff --exit-code HEAD -- deploy/staging/README.md` 通过。依照任务范围约束仅记录，不顺带修正；P7-05 保持未完成，不能声称全仓质量门禁通过。

除该门禁基线问题外，未发现本次范围内未完成的实现。真实环境性能、存储配置及发布恢复演练不由本地隔离验收替代；部署与业务接入仍在本次授权之外。本阶段在交付后停止。
