# 开发者手册

本手册维护当前系统规则与开发运行要求。设计方案和实施计划分别位于 `docs/design/`、`docs/plans/`，日常开发从本页进入。

## 按目的阅读

| 目的                     | 入口                                      |
| ------------------------ | ----------------------------------------- |
| 了解系统组成与边界       | [系统架构](architecture/overview.md)      |
| 查当前业务规则与开放范围 | [业务模块](modules/README.md)             |
| 准备环境并启动           | [本地开发](development/local-setup.md)    |
| 准备开发数据             | [开发数据](development/seed.md)           |
| 执行质量检查             | [检查与验证](development/verification.md) |
| 准备部署与运行检查       | [部署与运行](operations/deployment.md)    |
| 新增方案、计划或维护文档 | [文档治理](standards/documentation.md)    |

## 开发约束

| 专题                 | 权威入口                                                                                               |
| -------------------- | ------------------------------------------------------------------------------------------------------ |
| 工程原则、安全与提交 | [开发规范](standards/development.md)                                                                   |
| 后台页面与交互       | [前端规范](standards/admin-frontend.md)                                                                |
| 测试分类与资源隔离   | [测试规范](standards/testing.md)                                                                       |
| API 与错误           | [API 规范](standards/api.md)、[错误与异常](standards/errors.md)、[OpenAPI](../../openapi/openapi.yaml) |
| 数据与迁移           | [数据库规范](standards/database.md)                                                                    |
| 技术分层与协作       | [后端](architecture/backend.md)、[后台](architecture/admin-web.md)、[小程序](architecture/miniapp.md)  |
