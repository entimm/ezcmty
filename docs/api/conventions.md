# API 规范

## OpenAPI First 与契约一致性

[OpenAPI 入口](openapi/openapi.yaml) 及其引用文件是 API 契约的唯一权威来源。先设计契约，再实现 FastAPI 路由、Pydantic Schema 和测试。

FastAPI 自动生成的 OpenAPI 仅是实现结果，不作为另一套权威接口定义。实现必须通过契约检查。

## 文件组织

```text
docs/api/openapi/
├── openapi.yaml
├── modules/
│   └── system.yaml
└── components/
    ├── schemas.yaml
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

## 命名

- URL 使用资源名词。
- 函数和方法使用 `Verb + Object`。
- 标准 REST 无法表达的操作使用 `Resource + Action`。
- 错误响应、权限、幂等性和状态码必须在契约中明确。
