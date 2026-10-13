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

居民 API 不与物业管理 API 共用进程，但共享 Service、Repository、Model 和 Integration。

## 后端分层

```text
API → Service → Repository → Model
Service → Integration → 第三方服务
Worker → Service
```

路由层不直接访问数据库。Service 层负责业务规则、权限、数据范围、事务边界和状态流转。

## 会话

Redis 作为共享会话存储：

- 管理端使用安全 Cookie。
- 居民端使用独立会话令牌。
- 平台、物业、居民会话使用不同命名空间。
- Redis 不承担初期任务队列职责。

MySQL 保存业务数据，Redis 会话丢失时允许用户重新登录。

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

`xlife2` 仅是当前临时仓库目录名。代码、Python 包、前端包、容器服务、镜像、环境变量和 OpenAPI 标识不得依赖该名称。
