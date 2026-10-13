# 管理后台前端设计

## 工程与依赖

`apps/admin-web/` 以 [Ant Design Pro v6.0.3](https://github.com/ant-design/ant-design-pro/releases/tag/v6.0.3) 官方模板为基线，采用 Umi Max、React、Ant Design 和 ProComponents。运行组件与会话存储边界沿用 [系统架构](overview.md)。

核心依赖固定为以下版本，通过 pnpm 锁文件保证可重复安装；升级时显式修改依赖并验证兼容性。

| 依赖              | 版本     |
| ----------------- | -------- |
| Umi Max           | 4.7.3    |
| React / React DOM | 19.2.7   |
| Ant Design        | 6.6.0    |
| ProComponents     | 3.1.14-2 |

ProComponents 沿用该正式模板锁定的预发布版本，支持 Ant Design 6。pnpm 对齐 Umi 插件的 ProComponents 依赖，避免运行时混用不同组件主版本。

工程按实际需求保留模板能力。初始页面包括后台入口页、平台首页、物业首页和 404 页；真实登录与业务页面依据后续 OpenAPI 契约接入。认证接口尚未定义时，会话初始化为未认证状态。

## 双后台边界

平台与物业共用工程和静态构建产物，通过 Umi 配置路由分别进入 `/platform/*` 和 `/property/*`。两端各自使用 ProLayout、菜单、会话与权限上下文；共享组件不持有跨端身份状态。

- 平台作用域为 `platform_admin`，物业作用域为 `property_admin`；会话不能写入其他作用域。
- 路由与菜单权限由所属后台的会话上下文计算。前端权限用于页面展示与导航，服务端权限和数据范围执行要求见 [开发规范](../guidelines/development.md#安全)。
- 每端独立创建 QueryClient，并隔离 ProComponents 请求缓存。身份变更、退出、认证失效时，取消本端进行中的请求并重置本端缓存，避免旧身份响应回填。
- 请求客户端与认证失效处理绑定所属作用域；一个后台的 401 不清理另一个后台的会话或缓存。

## 请求与接口契约

平台和物业分别使用配置的 API 前缀与请求客户端，通过 Cookie 访问对应后端。请求和响应遵循 [API 规范](../api/conventions.md) 与 [错误与异常规范](../api/errors.md)，前端适配项目契约。

成功响应直接读取资源，错误解析 Problem Details；列表组件在使用分页接口时将契约中的 `items/total/page/page_size` 转换为组件所需的数据结构。当前端尚无对应接口契约时，不自动请求模板演示服务或构造登录接口。

## 开发、构建与检查

Umi 负责路由、开发服务器、热更新和生产构建，静态产物输出到 `apps/admin-web/dist/`。部署时 Nginx 对前端路由回退到 `index.html`，API 代理规则独立处理；部署边界见 [部署约定](deployment.md)。

工程保留 ESLint、Prettier 和 Vitest，TypeScript 使用 5.9.3，以满足现有 typescript-eslint 的兼容范围。Vitest 使用独立测试配置；Umi 生成文件不提交、不参与人工格式和 Lint 检查。

管理后台开发服务器固定监听 `127.0.0.1:5173`。启动器通过 [Node 开发入口](../../apps/admin-web/scripts/dev.cjs) 加载 Umi Max，并沿用批次身份登记、就绪和停止机制；该入口将 Umi 开发子进程意外退出报告为失败，开发端口校验阻止 Umi 在端口冲突时自动改用其他端口。开发入口约束见 [本地开发入口设计](local-development.md)，操作见 [本地开发指南](../guidelines/local-development.md)。

验证覆盖入口与双后台路由、权限和会话作用域、请求与缓存隔离、认证失效处理、类型检查、Lint、单元测试和构建，以及启动停止、端口冲突与清理回归。
