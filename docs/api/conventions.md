# API 规范

## OpenAPI First

`docs/api/openapi/` 下的多文件 OpenAPI 契约是 API 的权威来源。先设计契约，再实现 FastAPI 路由、Pydantic Schema 和测试。

## 文件组织

```text
docs/api/openapi/
├── openapi.yaml
├── modules/
│   └── <business-module>.yaml
└── components/
    ├── schemas.yaml
    ├── parameters.yaml
    ├── responses.yaml
    └── security-schemes.yaml
```

入口文件人工维护，并通过 `$ref` 引用模块和共享组件。模块文件按业务模块拆分，避免按进程集中成大文件。文件明显膨胀后再继续拆分。

## 校验和构建

使用 Redocly CLI：

```bash
pnpm api:lint
pnpm api:bundle
pnpm api:check
```

聚合文件属于构建产物，不作为人工维护对象。

## 命名

- URL 使用资源名词。
- 函数和方法使用 `Verb + Object`。
- 标准 REST 无法表达的操作使用 `Resource + Action`。
- 错误响应、权限、幂等性和状态码必须在契约中明确。

## 契约与代码

FastAPI 自动生成的 OpenAPI 仅是实现结果。实现必须通过契约检查，不能维护一套与 `docs/api/openapi/` 独立的接口定义。
