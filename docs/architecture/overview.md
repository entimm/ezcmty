# 系统架构概览

## 组件

系统由以下组件组成：

- 平台管理端
- 物业管理端
- 居民微信小程序
- Webhook 端
- 任务系统

后端使用一个 Python 包 `backend_app`，通过独立运行入口提供以下进程：

| 进程                 | 职责               |
| -------------------- | ------------------ |
| `platform-admin-api` | 平台管理接口       |
| `property-admin-api` | 物业管理接口       |
| `resident-api`       | 居民小程序接口     |
| `webhook`            | 外部回调接收和校验 |
| `worker`             | 异步任务执行       |

各 API 进程使用独立的应用 Service，共享 Domain、Repository、Model、Integration 和响应映射。后台业务编排与复用边界见 [后端业务边界与公共能力](backend-services.md)。

管理后台平台和物业功能共用 Ant Design Pro 项目，但保持独立路由、布局、会话和权限上下文；前端工程与缓存隔离见 [管理后台前端设计](admin-web.md)。

后台认证、管理员、角色权限和审计的共用规则见 [管理后台基础框架设计](../design/admin/foundation.md)。

## 后端分层

```text
API → Service → Domain
Service / Domain → Repository → Model
Service → Integration → 第三方服务
Service → Schema / Mapper
Worker → Service
```

- API 只负责 HTTP 请求处理、输入校验、认证入口和响应转换，不直接访问数据库。
- Service 负责各端业务编排、操作权限、数据范围、状态流转、会话生命周期和事务边界。
- Domain 按业务领域维护共用规则；与应用 Service、API Schema 和会话存储的依赖边界见 [后端业务边界与公共能力](backend-services.md#分层与职责)。
- Schema 定义请求与响应模型，Mapper 负责纯响应转换。
- 数据库访问统一通过 Repository。
- 第三方能力统一放入 Integration，由其负责第三方协议和外部能力封装。

## 会话

Redis 作为共享会话存储：

- 管理端使用安全 Cookie。
- 居民端使用独立会话令牌。
- 平台、物业、居民会话使用不同命名空间。
- Redis 不承担初期任务队列职责。

PostgreSQL 保存业务数据，Redis 会话丢失时允许用户重新登录。

## 目录

后端 Python 包根目录固定为：

```text
services/backend/src/backend_app/
```

API 模块固定为：

```text
backend_app/api/platform_admin/
backend_app/api/property_admin/
backend_app/api/resident/
backend_app/api/webhook/
```

## 项目命名

`xlife2` 仅是当前临时仓库目录名。代码、Python 包、前端包、运行服务、环境变量和 OpenAPI 标识不得依赖该名称。
