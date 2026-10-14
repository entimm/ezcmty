# API 规范

## OpenAPI First 与契约一致性

[OpenAPI 入口](openapi/openapi.yaml) 及其引用文件是 API 契约的唯一权威来源。先设计契约，再实现 FastAPI 路由、Pydantic Schema 和测试。

使用 OpenAPI 3.1。成功响应直接返回资源、数组或查询结果，不添加统一 `code/message/data` 包装；错误处理遵循 [错误与异常规范](errors.md)。

FastAPI 自动生成的 OpenAPI 仅是实现结果，不作为另一套权威接口定义。实现必须通过契约检查。

## 文件组织

```text
docs/api/openapi/
├── openapi.yaml
├── modules/
│   └── system.yaml
└── components/
    ├── schemas.yaml
    ├── errors.yaml
    ├── headers.yaml
    ├── responses.yaml
    └── security-schemes.yaml
```

入口文件人工维护，并通过 `$ref` 引用模块和共享组件。模块文件按业务模块拆分，避免按进程集中成大文件。文件明显膨胀后再继续拆分。

共享数据模型、参数、响应和安全方案放入 `components/`，相应文件按实际需要创建。

## 校验和构建

使用 Redocly CLI：

```bash
pnpm api:lint
pnpm api:bundle
pnpm api:check
```

聚合文件的维护方式遵循 [长期文档治理规范](../standards/documentation.md#单一权威来源)。

操作通过 `x-runtimes` 声明所属进程，值使用 `platform_admin_api`、`property_admin_api`、`resident_api` 或 `webhook`。检查逐进程比较归属的接口，同时拒绝遗漏或多暴露的接口，不要求所有进程实现全部业务接口。

`pnpm api:check` 还检查契约版本、错误目录生成文件及请求参数、请求体、响应状态、媒体类型、Schema、响应头和安全方案的一致性。错误目录修改后执行 `pnpm api:generate-errors`，生成文件不人工维护。

## 命名

- URL 使用小写、复数资源名词，多个单词用连字符连接。
- JSON 字段、路径参数和查询参数使用 `snake_case`，`operationId` 使用 `verbObject`。
- 函数和方法使用 `Verb + Object`。
- 标准 REST 无法表达的操作使用 `Resource + Action`。
- 错误响应、权限、幂等性和状态码必须在契约中明确。

实体标识的主键规则与对外格式见 [数据库规范的主键设计](../database/conventions.md#主键设计)。

## 路径、方法与状态

业务接口使用后端路径 `/v1/<resources>`，经现有端入口访问时为 `/api/<audience>/v1/<resources>`。运维接口 `/healthz`、`/readyz` 保持原路径；外部 Webhook 路径服从对接协议。

GET 用于读取，POST 用于创建或契约明确的业务操作，PUT 用于完整替换，PATCH 用于部分修改，DELETE 用于删除。创建成功通常使用 201，接受异步处理使用 202，无响应体成功使用 204，其余通常使用 200。错误状态规则由错误与异常规范维护。

`/readyz` 的依赖未就绪响应是运维状态数据：503 与 `application/json` 的 `ReadinessResponse`，不转换成业务错误包装。

## 分页、排序与筛选

需要分页的列表使用 `page`（默认 1，最小 1）和 `page_size`（默认 20，范围 1–100），返回 `items/total/page/page_size`。排序使用 `sort=created_at,-id`，仅允许契约列出的字段，并加入唯一键等稳定排序依据。

筛选参数逐项声明类型和允许值，不接受 SQL 表达式或任意字段名。公共参数在实际使用时放入 OpenAPI `components/` 复用，不预建未使用的参数或分页框架。

## 时间

时间戳使用带时区的 RFC 3339，响应统一使用 UTC `Z`；允许的时区偏移输入转换为 UTC，不接受缺少时区的时间戳。日期字段单独使用 `YYYY-MM-DD`。存储约束见 [数据库规范](../database/conventions.md)。

## 版本与兼容

路径中的 `v1` 表示业务 API 主版本，OpenAPI `info.version` 表示契约修订版本。运行时契约版本由生成的目录常量提供，配置不得宣称另一版本。

- 新增可选输入或兼容响应字段仍须评估消费者；客户端应容忍新增响应字段，对未知错误码按 HTTP 状态通用处理。
- 删除或重命名字段、增加必填输入、收紧允许值、更换错误结构或媒体类型、改变状态码或业务语义属于破坏性变更。
- 破坏性变更须说明影响、获得审查确认并制定迁移方案。已发布主版本需要兼容时通过新主版本过渡，不静默覆盖。
