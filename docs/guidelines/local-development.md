# 本地开发指南

本指南维护本地开发操作。启动器的模块职责、批次归属、就绪判断和故障处理见 [本地开发入口设计](../architecture/local-development.md)。

只验证代码时，安装依赖后进入[质量检查](#质量检查)，无需手动迁移、seed 或准备真实商户材料；集成测试自行建立隔离资源。查看页面和接口时，按下文准备本地数据库、Redis、配置与账号。命令应在需要验证的分支或 worktree 中执行，未另行说明时工作目录为仓库根目录。

## 开发环境

- Python 3.14.x（默认版本见 [.python-version](../../.python-version)，版本范围由 [后端项目配置](../../services/backend/pyproject.toml) 的 `requires-python` 声明）
- `uv`
- Node.js（默认使用 [.node-version](../../.node-version) 指定的 24.x，具体版本须满足 [package.json](../../package.json) 的 `engines.node`）
- `pnpm`
- PostgreSQL 18.x 和 Redis（默认复用本机已安装实例）
- 微信开发者工具

## 初始化本地环境

在仓库根目录执行：

```bash
make install
```

`make install` 按现有锁文件安装后端开发依赖与整个 pnpm 工作区依赖。

仅首次初始化且目标文件不存在时复制配置；已有文件直接编辑：

```bash
cp services/backend/.env.example services/backend/.env
```

[services/backend/.env.example](../../services/backend/.env.example) 是本地后端配置模板，仅包含 `APP_*`，默认连接本机 PostgreSQL 和 Redis。

启动前，使用你本机已有的管理方式启动 PostgreSQL 和 Redis，并确认已有数据库、账号及访问权限满足应用配置。开发入口仅检查已有配置与依赖；检查范围及处理方式见 [启动流程](../architecture/local-development.md#启动流程)。

支付本地联调使用独立数据库及 Redis 资源。`make migrate` 和 seed 会写入配置指向的数据库；执行前核对目标与已有环境变量，不能将隔离联调命令用于既有业务数据库。

编辑 `services/backend/.env`：

```dotenv
APP_DATABASE_URL=postgresql+psycopg://你的账号:你的密码@127.0.0.1:5432/已有数据库
APP_REDIS_URL=redis://127.0.0.1:6379/0
APP_LOG_LEVEL=INFO
```

URL 中的账号、密码须按 URL 规则编码。若 Redis 需要认证，配置对应凭据。模板中的数据库名和凭据仅为示例，需按本机已有实例填写。数据库须使用 UTF8 及确定性、大小写敏感的排序规则；PostgreSQL 18 可使用 builtin `C.UTF-8` locale。应用与迁移连接会显式设置 UTC，连接、语句及锁超时见 [数据库规范](../database/conventions.md#连接事务与查询)。

后端依赖检查及所有后端进程的工作目录固定为 `services/backend/`，沿用现有 Settings 读取该处 `.env`；**已有环境变量优先于 `.env`**。仓库根目录的 `.env` 不作为后端配置来源。包含 Worker 的启动批次需要 `APP_LOG_LEVEL=INFO` 或 `DEBUG`，以观察现有启动标记。配置及运行日志均不提交 Git。

通用导入的私有文件目录由 `APP_IMPORT_STORAGE_ROOT` 指定，本地默认 `services/backend/.dev/imports`（相对后端工作目录为 `.dev/imports`）。平台、物业 API 与现有 Worker 必须使用同一目录；目录和对象分别使用 `0700`、`0600` 权限。测试显式注入独立临时目录。生产环境必须配置私有持久目录的绝对路径；此约定不执行目录部署或真实数据操作。生产导入类型按注册表开放，业务范围见 [账单批量导入](../design/property/bill-imports.md) 和 [房屋批量导入](../design/property/house-imports.md)；通用框架测试使用测试目录内的独立定义与适配器。

管理后台使用 Umi 环境配置，可按需参考 [apps/admin-web/.env.example](../../apps/admin-web/.env.example) 配置该目录的本地环境文件。`UMI_APP_NAME` 配置公开应用名称，`UMI_APP_PLATFORM_API_BASE` 和 `UMI_APP_PROPERTY_API_BASE` 分别配置同源 API 前缀，默认是 `/api/platform`、`/api/property`；这些 `UMI_APP_*` 值会进入浏览器构建产物，不得包含密钥。开发代理将对应前缀转发到本机 8001、8002 并移除端入口前缀。单独启动管理后台无需 PostgreSQL、Redis 或后端配置。

## 开发命令

### 平台后台初始化

配置好已有 PostgreSQL 和 Redis 后，在仓库根目录执行数据库迁移，再执行受控初始化：

```bash
make migrate
make init-platform-admin
```

默认登录名为 `bootstrap`，显示名称为 `平台管理员`。可通过 Make 参数覆盖：

```bash
make init-platform-admin LOGIN_NAME=your-admin DISPLAY_NAME="平台管理员"
```

登录名输入允许任意大小写，服务端统一为小写；公司和小区编码统一为大写，接口返回规范化后的形式。规范化与唯一性约束见 [数据库规范](../database/conventions.md#字符串与约束)。

初始化命令交互输入并确认密码，密码长度为 12–128 字符。已有有效超级管理员或同名账号时拒绝初始化，不能覆盖现有密码或授权。首次登录必须修改密码。

需要清空本地开发数据并重新迁移时，在仓库根目录执行：

```bash
make stop
make db-reset
make migrate
make init-platform-admin
```

`make db-reset` 使用后端配置连接数据库，仅允许显式配置 `APP_ENV=local/test`，并要求输入实际数据库名确认。

命令在同一事务中清空并重建 `public`，删除其中全部数据、表、触发器函数和 Alembic 版本记录；依赖这些对象的其他 schema 对象也可能被级联删除。重建后恢复 `public` 的默认所有者和访问权限。

数据库本身、编码和排序规则保留。连接账号应具有数据库所有者权限，无需 `CREATEDB`。

管理员会话空闲和绝对有效期分别由 `APP_ADMIN_SESSION_IDLE_SECONDS`、`APP_ADMIN_SESSION_ABSOLUTE_SECONDS` 配置；绝对有效期不能短于空闲有效期。`APP_ADMIN_TRUSTED_ORIGINS` 使用 JSON 数组，列出管理页面的完整 Origin；写请求必须来自其中之一。生产环境配置实际 HTTPS Origin，Cookie 会开启 Secure。

两端 Cookie 路径分别由 `APP_PLATFORM_ADMIN_COOKIE_PATH`、`APP_PROPERTY_ADMIN_COOKIE_PATH` 配置，必须与浏览器访问的 API 前缀一致且互不包含。登录尝试限制由 `APP_ADMIN_LOGIN_LIMIT` 和 `APP_ADMIN_LOGIN_WINDOW_SECONDS` 配置，按账号和来源 IP 分别执行。

平台与物业的域名和页面路径规则见 [域名与页面路径](../architecture/admin-web.md#域名与页面路径)。直接访问开发服务器时使用 `/platform`、`/property`；域名站点从 `/` 进入，未登录时跳转本端 `/login`。物业使用平台开通的公司管理员账号，公司和账号均须启用；首次登录要求改密，流程见 [物业管理端登录与基础工作台设计](../design/property/workbench.md)。

### 本地域名站点

推荐访问 `https://platform.ezcmty.test:8443/`、`https://property.ezcmty.test:8443/`。本地 HTTPS 的组件、证书和恢复约定见 [部署约定](../architecture/deployment.md#本地管理后台-https)。普通 HTTP 的 `.test` 域名不属于安全上下文，不能直接使用 `crypto.randomUUID()`。

将两个域名解析到 `127.0.0.1`；已有 dnsmasq 与 `/etc/resolver/test` 时先用 `dscacheutil -q host -a name platform.ezcmty.test` 验证，复用已有解析。Nginx 在回环地址的 8443 端口提供 HTTPS，再转发到 `127.0.0.1:5173`；8080 保留为 HTTP 开发入口。

先设置证书目录和 OpenSSL 路径。Homebrew OpenSSL 在 Apple Silicon Mac 上通常位于 `/opt/homebrew/opt/openssl@3/bin/openssl`，Intel Mac 按实际安装前缀调整：

```bash
TLS_ROOT="$HOME/.config/local-https"
TLS_OPENSSL=/opt/homebrew/opt/openssl@3/bin/openssl
umask 077
mkdir -p "$TLS_ROOT/ca" "$TLS_ROOT/certs"
```

仅首次在本机建立 CA 时执行以下命令；已有 CA 时验证并复用，不能覆盖其私钥：

```bash
"$TLS_OPENSSL" req -x509 -newkey rsa:2048 -nodes -sha256 -days 3650 \
  -subj '/CN=Local Development Root CA/O=Local Development' \
  -keyout "$TLS_ROOT/ca/root-ca.key" -out "$TLS_ROOT/ca/root-ca.pem" \
  -addext 'basicConstraints=critical,CA:TRUE,pathlen:0' \
  -addext 'keyUsage=critical,keyCertSign,cRLSign' \
  -addext 'subjectKeyIdentifier=hash'
```

首次建立 CA 或已有 CA 尚未受系统信任时，单独执行以下导入命令，无需重新生成 CA：

```bash
TLS_ROOT="$HOME/.config/local-https"
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain "$TLS_ROOT/ca/root-ca.pem"
```

系统钥匙串导入需要管理员认证；导入的是根 CA 公共证书 `root-ca.pem`。后续签发及续期站点证书复用该 CA，无需重复导入。生成双域名服务端证书：

```bash
"$TLS_OPENSSL" req -new -newkey rsa:2048 -nodes -sha256 \
  -subj '/CN=platform.ezcmty.test/O=Local Development' \
  -keyout "$TLS_ROOT/certs/ezcmty.test.key" -out "$TLS_ROOT/certs/ezcmty.test.csr"
cat > "$TLS_ROOT/certs/ezcmty.test.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
subjectAltName=DNS:platform.ezcmty.test,DNS:property.ezcmty.test
EOF
"$TLS_OPENSSL" x509 -req -sha256 -days 365 \
  -in "$TLS_ROOT/certs/ezcmty.test.csr" \
  -CA "$TLS_ROOT/ca/root-ca.pem" -CAkey "$TLS_ROOT/ca/root-ca.key" \
  -CAserial "$TLS_ROOT/ca/root-ca.srl" -CAcreateserial \
  -extfile "$TLS_ROOT/certs/ezcmty.test.ext" -out "$TLS_ROOT/certs/ezcmty.test.pem"
chmod 700 "$TLS_ROOT" "$TLS_ROOT/ca" "$TLS_ROOT/certs"
chmod 600 "$TLS_ROOT/ca/root-ca.key" "$TLS_ROOT/certs/ezcmty.test.key"
"$TLS_OPENSSL" verify -CAfile "$TLS_ROOT/ca/root-ca.pem" \
  -purpose sslserver -verify_hostname platform.ezcmty.test "$TLS_ROOT/certs/ezcmty.test.pem"
"$TLS_OPENSSL" verify -CAfile "$TLS_ROOT/ca/root-ca.pem" \
  -purpose sslserver -verify_hostname property.ezcmty.test "$TLS_ROOT/certs/ezcmty.test.pem"
```

更改前将现有 Nginx 站点配置与两个本地环境文件备份到仓库外或 `.dev/`，备份目录权限设为 `700`、文件权限设为 `600`。从仓库根目录安装 [Nginx 示例](../../apps/admin-web/config/nginx.local.conf)，替换证书目录占位符：

```bash
sed "s|LOCAL_HTTPS_PATH|$TLS_ROOT|g" apps/admin-web/config/nginx.local.conf \
  > /opt/homebrew/etc/nginx/servers/ezcmty.test.conf
nginx -t -c /opt/homebrew/etc/nginx/nginx.conf
nginx -s reload
```

在 `services/backend/.env` 的 `APP_ADMIN_TRUSTED_ORIGINS` 中加入两个完整 HTTPS Origin（包含 `:8443`，不包含末尾 `/`），保留需要的 HTTP 与直连开发 Origin；Cookie 路径使用对应 API 前缀。域名变更时同步配置前端 hostname、证书 SAN 和后端可信 Origin。

移除 `apps/admin-web/.env.local` 中固定指向 HTTP 的 `SOCKET_SERVER`，让 Umi 按当前页面来源连接同源 WSS。浏览器或系统使用代理时，将 `platform.ezcmty.test`、`property.ezcmty.test` 配置为直连。环境文件不会自动触发后端配置重载；通过现有开发入口停止并重启所属服务批次。单一完整后台批次可使用 `make stop`、`make dev-bg`；多个批次应记录原服务组合并分别恢复。

使用两个 HTTPS 地址确认浏览器无证书警告，控制台执行 `window.isSecureContext` 应为 `true`、`crypto.randomUUID()` 应返回 UUID；网络面板应显示同源 WSS 连接成功。核对登录、写请求的 Origin 校验及两端 API 隔离。验证期间保留 8080，续期时备份并重新签发站点证书，验证证书链后检查、重载 Nginx；恢复时还原上述配置备份并重启受影响服务。

出现 `Your connection is not private` 时，先记录浏览器错误码。`NET::ERR_CERT_AUTHORITY_INVALID` 通常表示签发 CA 尚未受信任；按上文导入已有 CA，然后验证 macOS 系统信任及实际 HTTPS 入口：

```bash
TLS_ROOT="$HOME/.config/local-https"
/usr/bin/security verify-cert -c "$TLS_ROOT/certs/ezcmty.test.pem" \
  -p ssl -s platform.ezcmty.test
/usr/bin/security verify-cert -c "$TLS_ROOT/certs/ezcmty.test.pem" \
  -p ssl -s property.ezcmty.test
/usr/bin/curl --noproxy '*' -I https://platform.ezcmty.test:8443/
/usr/bin/curl --noproxy '*' -I https://property.ezcmty.test:8443/
```

上述 `verify-cert` 应报告验证成功，系统 `curl` 应通过默认信任返回 HTTP 响应；使用 `--cacert` 验证成功只证明指定 CA 下的证书链有效，不能证明系统已经信任。系统验证通过后刷新页面；Chrome 仍保留旧警告时，保存正在编辑的内容后完全退出并重新打开 Chrome。不要通过跳过浏览器警告或 `curl -k` 判定验收通过。

`NET::ERR_CERT_COMMON_NAME_INVALID` 时核对访问域名与证书 SAN；`NET::ERR_CERT_DATE_INVALID` 时核对系统时间和证书有效期。若磁盘证书验证成功而实际 HTTPS 入口仍失败，核对 Nginx 的证书路径、域名解析及代理直连设置，检查配置并重载 Nginx。

### 服务命令

全部命令在仓库根目录执行；`make` 默认显示帮助。

| 命令                      | 用途                                                                        |
| ------------------------- | --------------------------------------------------------------------------- |
| `make install`            | 安装后端及前端工作区开发依赖                                                |
| `make migrate`            | 执行 Alembic 数据库迁移，升级到 `head`                                      |
| `make dev`                | 前台同时启动四个 API、Worker 和管理后台                                     |
| `make dev-bg`             | 后台同时启动同样六个服务，全部就绪后返回                                    |
| `make stop`               | 停止本仓库所有开发入口登记的批次                                            |
| `make platform`           | 前台启动平台管理 API，8001                                                  |
| `make property`           | 前台启动物业管理 API，8002                                                  |
| `make client`             | 前台启动客户端 API，8003                                                    |
| `make webhook`            | 前台启动 Webhook，8004                                                      |
| `make worker`             | 前台启动持久任务 Worker                                                     |
| `make admin`              | 前台启动管理后台，5173                                                      |
| `make miniapp-build`      | 构建小程序到 `apps/miniapp/dist/`，通过微信开发者工具打开小程序项目         |
| `make check`              | 先运行根目录 Prettier，再依次运行后端、前端和 OpenAPI 检查                  |
| `make check-backend`      | 后端源码、devtools、测试及仓库 scripts 的 Ruff、mypy、pytest                |
| `make check-frontend`     | 管理后台与小程序 typecheck、lint、test、build，各入口自动生成 OpenAPI 类型  |
| `make check-api`          | `pnpm api:check`：OpenAPI lint、前端类型生成、bundle、contract              |
| `pnpm api:generate-types` | 从权威契约刷新本地前端类型声明，产物由 Git 忽略                             |
| `make test-unit`          | 后端单元测试                                                                |
| `make test-integration`   | 后端快速集成测试，排除专用 PostgreSQL/Redis 并发测试和进程生命周期          |
| `make test-contract`      | 后端与权威 OpenAPI 的契约一致性测试                                         |
| `make test-postgresql`    | 使用独立临时实例执行真实 PostgreSQL/Redis 测试                              |
| `make test-full`          | 全部后端、管理后台和小程序测试，包含真实依赖与进程生命周期，生成 JUnit 报告 |
| `make help`               | 显示全部命令及用途                                                          |

小程序不作为常驻进程；构建后使用微信开发者工具运行。

### 账单支付配置与运行边界

按[平台后台初始化](#平台后台初始化)完成迁移和管理员准备，按需使用[开发数据填充](#开发数据填充)生成账单，再按[运行、地址与日志](#运行地址与日志)启动服务。`billing` seed 生成账单、线下收款和冲正等演示数据，不生成微信支付成功、分账或解冻事实。

微信支付配置沿用后端 `APP_*` 环境变量，完整名称见[配置模板](../../services/backend/.env.example)中的支付段。
`APP_WECHATPAY_MERCHANT_PRIVATE_KEY` 是服务商签名私钥的 PEM，
`APP_WECHATPAY_API_V3_KEY` 是 APIv3 密钥；验签公钥或证书以
`APP_WECHATPAY_VERIFICATION_KEYS` 的 JSON 对象按公钥 ID／证书序列号配置，
`APP_WECHATPAY_ENCRYPTION_KEY_ID` 选择敏感字段加密公钥。AppID 复用平台小程序配置。
支付通知地址和分账动账通知地址分别配置，均使用可达的 HTTPS 地址。
这些材料只放在受控环境配置中，不写入任务证据或日志。

`APP_PAYMENT_NEW_ORDERS_ENABLED` 默认关闭，只控制新支付创建。停止新支付时保留
Webhook 与 Worker，已有订单仍须查单、确认入账、分账、解冻及核对；不能以停掉任务进程代替关闭新单入口。

缺少商户材料时 Worker 仍可启动调度；就绪标记不证明渠道可用或资金执行成功。普通服务启动不提供模拟支付成功入口，无真实材料的支付流程验证使用[账单支付专项验证](#账单支付专项验证)中的测试替身。真实商户请求、付款、分账、解冻及新单开放须取得相应授权，发布条件见[账单支付发布与恢复准备](../plans/payment/bill-payments-release.md)。

### 小程序构建与运行

小程序使用平台统一 AppID。构建时自动读取 `apps/miniapp/.env.local`，已有环境变量优先于该文件；本地文件不提交 Git。首次使用从[配置模板](../../apps/miniapp/.env.example)复制，已有文件直接编辑：

```bash
cp apps/miniapp/.env.example apps/miniapp/.env.local
make miniapp-build
```

`MINIAPP_API_BASE_URL` 指定后端地址；模板和未配置时默认直连本地客户端 API `http://127.0.0.1:8003`。HTTPS 网关地址包含 `/api/client`，不包含 `/v1`。API 地址不能包含凭证、查询串或片段；`NODE_ENV=production` 时必须使用 HTTPS。平台 AppID 在 `project.config.json` 配置，产品名称为“美好社区”。

客户端进程入口为 `backend_app.runtimes.client_api:app`，统一登录、恢复和退出使用 `/v1/client-sessions` 及其 `/current` 资源。会话使用 `APP_CLIENT_SESSION_IDLE_SECONDS`、`APP_CLIENT_SESSION_ABSOLUTE_SECONDS`；公共登录、手机号和限流窗口使用 `APP_CLIENT_LOGIN_LIMIT`、`APP_CLIENT_PHONE_LIMIT`、`APP_CLIENT_RATE_WINDOW_SECONDS`。居民认领限流仍使用 `APP_RESIDENT_CLAIM_LIMIT`，完整默认值见[后端配置模板](../../services/backend/.env.example)。

当前尚未发布，仅用于开发联调，本次直接切换到 `/api/client`，不保留旧 API 兼容入口。旧居民 Token 不自动升级为客户端凭据，切换后重新微信认证。既有开发环境须同步配置变量、网关和小程序 API 地址，并按[客户端迁移与发布](../design/client/architecture.md#迁移与发布)处理同环境、同用户的非敏感业务恢复信息；开发命令不额外启动旧居民进程，也不修改实际部署或业务数据。

API 地址改变时，只有发布者已确认旧、新地址属于同一部署环境、沿用同一用户及业务数据，才可配置 `MINIAPP_API_STORAGE_MIGRATIONS`。该构建变量为 JSON 数组，每项包含 `from`、`to`；只有 `to` 等于当前 `MINIAPP_API_BASE_URL` 的显式映射生效，不根据 URL 相似或同域名推断环境。可在 `apps/miniapp/.env.local` 中配置，例如同一开发环境的网关前缀调整：

```dotenv
MINIAPP_API_BASE_URL=https://api.ezcmty.test/api/client
MINIAPP_API_STORAGE_MIGRATIONS='[{"from":"https://api.ezcmty.test/api/resident","to":"https://api.ezcmty.test/api/client"}]'
```

迁移只在新的客户端会话经服务端确认是同一用户后，读取该用户的选房 ID 和非敏感原支付恢复依据；不迁移旧令牌、权限或敏感草稿，不读取其他用户的数据。先确认新副本写入成功再清理对应旧键，失败保留原依据，不生成新幂等键重复付款。不配置映射时不跨 API 地址迁移；变量改变后重新构建小程序。

在微信开发者工具打开 `apps/miniapp/`，项目输出位于 `dist/`。IP 入口用于开发者工具联调，需关闭合法域名校验；真机需要可访问的 HTTPS 域名及微信后台合法域名配置，服务端配置见 `services/backend/.env.example`。

项目配置启用自定义预处理，在开发者工具手动编译、预览和上传前通过 `scripts/devtools-build.sh` 执行 `pnpm run build`，确保产物包含当前源码和环境配置；命令依赖本机可用的 Node.js、pnpm 和已安装的项目依赖。macOS 的预处理脚本补充 Homebrew 常用命令目录，找不到 Node.js 或 pnpm 时尝试初始化已有 fnm，以兼容开发者工具未继承终端 PATH 的情况。修改项目配置后重新打开项目；文件热更新不触发编译前预处理。直接打开 `dist/` 时只读取既有产物，不执行源项目的预处理命令。终端仍可通过 `make miniapp-build` 主动构建。

每次构建默认按北京时间生成版本 `YYYYMMDDHHmmss`，可用 `MINIAPP_BUILD_VERSION` 覆盖。版本收纳于个人中心“关于美好社区”，不占用首页。预览和上传前重新构建，确保版本对应当前产物。

请求错误先展示中文原因和下一步；不向用户展示或记录原始网络异常、接口查询串、微信 code、手机号输入、令牌和支付凭证。网络失败与认证失效分别处理，未知写入结果使用原幂等键恢复。

连接本地后端的构建示例（替换为对应平台小程序 AppID）：

```bash
MINIAPP_API_BASE_URL=http://127.0.0.1:8003 \
make miniapp-build
```

实际微信登录和手机号授权需在项目配置中填写平台 AppID，并在后端配置匹配的 `APP_WECHAT_MINIAPP_APP_ID`、`APP_WECHAT_MINIAPP_APP_SECRET`；仅配置 AppID 不提供登录凭据。构建变量变更后重新构建。

`pnpm --filter client-miniapp test` 验证会话隔离、身份选择、请求恢复和选房交互。构建后可运行 `pnpm --filter client-miniapp check:native` 调用微信开发者工具的 WXML/WXSS 编译器；默认查找 macOS 安装目录，其他环境通过 `MINIAPP_WCC`、`MINIAPP_WCSC` 指定编译器绝对路径。此检查要求本机已安装微信编译器，不能替代体验版登录及手机号授权的真机验收。

## 开发数据填充

seed 的场景、恢复与生产隔离规则见[开发数据填充设计](../architecture/development-seed.md)。工具只在源码检出中可用，所有业务数据通过现有 Service 写入。

先准备已迁移的开发 PostgreSQL 和 Redis，在 `services/backend/.env` 中显式配置 `APP_ENV=local`（隔离测试环境可以为 `test`）及 `SEED_ENABLED=1`。未显式配置环境、环境不是 `local` 或 `test`，或未启用开关时拒绝写入。已有环境变量仍优先于 `.env`。

```bash
make seed-list
make seed-plan SCENARIOS="property housing" SEED_ARGS="--set property.companies=3 --set housing.houses_per_unit=20"
make seed SCENARIOS="property housing" SEED_ARGS="--set property.companies=3 --set housing.houses_per_unit=20 --workers=2"
make seed                         # 默认全部场景；每次新增一批
make seed-resume RUN_ID=<批次标识> # 固定原批次参数续跑
make seed-coverage                # 只读核对实际数据库的表覆盖
```

`seed-plan` 和 `seed-list` 不连接数据库。写入前会打印数量估算，并检查迁移版本、表覆盖和 Redis。命令失败返回非零，保留已经提交的数据与上下文；重复执行 `seed` 是新批次，修复失败原因后应使用 `seed-resume` 完成原批次。

数量配置优先级为场景默认值、TOML 文件、`--set`。配置文件路径相对于 `services/backend/`；完整示例为 [example.toml](../../services/backend/devtools/seed/example.toml)：

```bash
make seed-plan SEED_ARGS="--config devtools/seed/example.toml"
make seed SEED_ARGS="--config devtools/seed/example.toml --set housing.houses_per_unit=50 --workers=2"
```

`SCENARIOS` 支持 `admin`、`property`、`housing`、`billing`，多个名称用空格分隔；`all` 选择全部。`billing` 依赖 `housing`，后者依赖 `property`，共享依赖只运行一次。未显式选择 `property` 时，默认准备一家物业、一个小区和一个物业管理员；可以覆盖其 `property.*` 前置参数。单独运行 `admin` 不生成物业数据。配置不得包含未选择且不属于依赖的场景。账单四张表由 `billing` 声明覆盖。

| 场景     | 数量参数                | 默认值与范围                                                      |
| -------- | ----------------------- | ----------------------------------------------------------------- |
| admin    | accounts                | 新增平台演示账号 3 个，允许 0–100000；空库初始化执行账号另计      |
| admin    | roles                   | 新增自定义角色 2 个，允许 1–10000；系统角色另计                   |
| property | companies               | 新增物业公司 2 家，允许 1–10000                                   |
| property | communities_per_company | 每公司 2 个小区，允许 1–10000                                     |
| property | admins_per_company      | 每公司 3 个账号，允许 1–10000                                     |
| housing  | phases_per_community    | 每小区 1 个分期，允许 0–100                                       |
| housing  | buildings_per_community | 每小区总共 2 栋楼，允许 1–10000；有分期时交替覆盖根楼栋和分期楼栋 |
| housing  | units_per_building      | 每栋 2 个单元，允许 0–100                                         |
| housing  | houses_per_unit         | 每单元 3 套房，允许 0–100000                                      |
| housing  | houses_per_building     | 每栋直接挂载 1 套房，允许 0–100000，与单元房屋相加                |
| housing  | owners_per_house        | 每套房 2 条业主记录，允许 0–100                                   |

账单联调示例（仓库根目录执行，每次 `seed` 都追加新批次）：

```bash
make seed-plan SCENARIOS=billing
make seed SCENARIOS=billing
make seed-plan SCENARIOS=billing SEED_ARGS="--set property.companies=2 --set property.communities_per_company=2 --set housing.buildings_per_community=2 --set housing.units_per_building=2 --set housing.houses_per_unit=5 --set housing.houses_per_building=1 --set housing.owners_per_house=1 --set billing.start_month=2026-08 --set billing.end_month=2026-12 --set billing.basis_versions_per_house=4 --set billing.bill_months_per_house=5"
```

将最后一条的 `seed-plan` 改为 `seed` 即按指定数量填充。仅选择 `billing` 的默认规模为 14 套房、28 条业主记录、56 个依据版本、100 张账单（含重建前的作废旧账单）、313 条操作和 234 条收款及冲正明细。平台执行账号、物业账号与其他前置对象另计。

| billing 参数                                                              | 默认值与范围 / 含义                                                                                                                                                 |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| start_month / end_month                                                   | `YYYY-MM` 闭区间，默认当月前两月至后两月，允许 1–120 个月；解析后随批次固定                                                                                         |
| basis_versions_per_house                                                  | 每套房 4 个依据版本，允许 0–100；0 时仅生成手填账单                                                                                                                 |
| bill_months_per_house                                                     | 默认全部月份，也可用 `--set billing.bill_months_per_house=all`；允许 0–120 且不超过范围，从起始月连续取指定月份数；0 时只生成依据                                   |
| min_receivable_cents / max_receivable_cents                               | 正金额范围 10000–50000 分，允许 2–9007199254740991，最小值不超过最大值；为足额分拆收款及纠错，最小值须至少为 `4 × (additional_receipts_per_bill + 1)`；零元样例另计 |
| unpaid_weight / partially_settled_weight / settled_weight / voided_weight | 房屋月份的待缴、部分结清、结清、作废权重 `4 / 2 / 3 / 1`，各允许 0–100，不能全为零；结清包含零元，重建额外产生作废行，实际状态行数以报告为准                        |
| additional_receipts_per_bill                                              | 每张适用正金额账单追加收款 2 次，允许 0–20；适用于部分结清及非建账即全额结清样例；0 时在建账时登记目标已缴金额                                                      |
| amount_corrections_per_bill                                               | 每张适用正金额账单纠正金额 1 次，允许 0–20；适用于部分结清及非建账即全额结清样例；纠错对象为最后一次登记，最终达到目标已缴金额                                      |
| date_corrections_per_bill                                                 | 每张正金额且有已缴的账单纠正收款日期 1 次，允许 0–20，保持金额不变                                                                                                  |
| reversals_per_bill                                                        | 每张待缴或部分结清账单演示误登记并撤销 1 次，允许 0–20；每次生成一条误收款与一条反向流水，净已缴不变                                                                |
| rebuilds_per_bill                                                         | 每个待缴房屋月份作废并新建 1 次，允许 0–10；每次增加一张作废旧账单，仍只有一张有效账单                                                                              |

依据默认依次覆盖面积单价、不同月份的固定正金额、同月追加纠错及未来固定零元。在同月纠错前先建账，旧账单保留原依据和金额。操作采用正式 Service、幂等键与审计，沿用批次追加和续跑机制。外部编号及到期日的组合自动轮换，收款日期不晚于批次固定业务日期。只操作本批次新建对象；生成账单完成后才执行房屋及祖先的演示停用。

`report.json` 的 `billing` 列出本批次实际表条数、月份、状态、金额来源、操作及明细分布、金额合计、覆盖项与一致性检查。`checks` 均为 0 表示核验通过，有异常时命令失败；小规模、减少依据版本或关闭操作后未覆盖的样例列入 `missing_coverage`。账单权重不会为凑齐覆盖而额外生成未配置的房屋、月份或依据。

每组演示账号按顺序循环生成正常、待首次改密、停用账号；每家公司第一个账号保持可用于填充。多个角色时停用最后一个角色；多个小区或公司时在房屋填充完成后停用最后一个。房屋场景在创建子数据后停用末尾分期，以及存在多个同类记录时的末尾楼栋、单元、房屋和业主，以覆盖直接停用和祖先停用状态。数量少时不能覆盖所有状态；`report.json` 列出实际表记录、启停状态与未覆盖项目。

空库自动调用现有初始化 Service 建立开发执行账号，并完成首次改密。工具创建的执行账号凭据存储在 `.dev/seed/operator-<数据库指纹>.json`，后续批次复用。若数据库已有平台账号且没有工具凭据，配置已完成首次改密的平台超级管理员 `SEED_LOGIN_NAME` 和 `SEED_PASSWORD`；不要把密码放进命令参数或提交的配置。已有账号不会被重置。CLI 的会话与两类登录限流使用独立 Redis 键前缀，命名和隔离边界见[Redis 隔离](../architecture/development-seed.md#redis-隔离)。CLI 登录沿用账号与来源限流，来源按执行账号区分；触发限流时保留批次，等待窗口恢复或调整开发环境已有的登录限制后续跑。

每次运行输出 `.dev/seed/<run_id>/`。`accounts.md` 和 `accounts.json` 只包含所属批次、场景、登录端、登录名、显示名称、密码、所属物业公司七项；平台公司的值为空，登录端使用 `platform_admin`、`property_admin`。清单包含创建成功的正常、待改密和停用账号；密码为工具最后确认设置的值，人工改密后不会自动更新。失败时也导出已确认账号，未确认的改密结果需续跑核对后再使用。

`state.json` 保存参数和批次状态，`context.sqlite3` 增量保存步骤、结果及凭据。保存整个批次目录才能续跑，不手工编辑上下文。同一批次不能并发执行；数据库身份、迁移版本、场景版本或已生成数据发生不兼容变化时停止恢复。目录权限为 0700，文件为 0600，`.dev/` 不进入 Git。账号文件由受限上下文导出，普通日志不输出密码。

`--workers` 为并发填充房屋及其账单的公司数，默认 1，范围 1–8；同公司有序执行，物业接入顺序执行。所有操作保持 Service 原有事务与审计，参数按需生成，本地上下文逐步持久化；运行中约每 5 秒报告完成步骤与速度。生产数据库的持久化、网络延迟和数据规模会影响速度，测试环境的吞吐不能直接作为部署环境指标。

验证命令（在 `services/backend/` 执行，使用独立临时 PostgreSQL/Redis，不访问开发业务数据库）：

```bash
APP_RUN_POSTGRESQL_TESTS=1 uv run pytest tests/unit/seed tests/integration/postgresql/test_seed.py tests/integration/postgresql/test_seed_billing.py tests/integration/postgresql/test_seed_sessions.py --require-all-tests
APP_RUN_POSTGRESQL_TESTS=1 uv run pytest tests/integration/postgresql/test_seed.py::test_thousand_houses_have_exact_counts_and_resume_without_growth --require-all-tests -s
```

## 运行、地址与日志

前台运行：

```bash
make dev
```

日志标明所属服务，全部服务就绪后显示地址。四个 API 默认开启 Uvicorn 热重载，监听 `services/backend/src/`；管理后台使用 Umi 热更新，开发端口固定且不自动切换。所有服务仅监听本机 `127.0.0.1`。

| 服务         | 访问地址                                                                                                                       |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| 平台管理 API | http://127.0.0.1:8001/docs                                                                                                     |
| 物业管理 API | http://127.0.0.1:8002/docs                                                                                                     |
| 客户端 API   | http://127.0.0.1:8003/docs                                                                                                     |
| Webhook      | http://127.0.0.1:8004/docs                                                                                                     |
| 平台管理页面 | http://127.0.0.1:5173/platform                                                                                                 |
| 物业管理页面 | http://127.0.0.1:5173/property                                                                                                 |
| Worker       | 无 HTTP 入口；读取实际任务表并启动调度、注册业务 Handler 后输出 `worker_ready scheduler=running task_handlers=N`，`N` 为正整数 |

启动入口会等待全部所选服务通过各自的 [就绪判断](../architecture/local-development.md#就绪判断)，再报告启动成功。

后台运行：

```bash
make dev-bg
```

后台协调器与服务脱离当前终端，关闭终端后继续运行。全部服务就绪后，命令显示批次、地址、日志目录与停止命令。前后台使用相同的协调、就绪及故障清理逻辑。

每批日志位于 `.dev/run/<批次 ID>/`：`platform.log`、`property.log`、`client.log`、`webhook.log`、`worker.log`、`admin.log`，以及记录启动、重载、失败和停止原因的 `coordinator.log`。该目录的 `state.json` 保留批次最终状态，仓库活动登记位于 `.dev/run/state.json`。整个 `.dev/` 已加入 Git 和 Prettier 忽略规则。

启动、单次探测、热重载恢复和停止的默认时限见 [时间限制](../architecture/local-development.md#时间限制)。正常热重载及实际 API 子进程故障的识别方式见 [API 热重载与故障识别](../architecture/local-development.md#api-热重载与故障识别)。

## 停止与启动冲突

前台的 `Ctrl+C` 只停止本次启动的批次，包括热重载子进程；也可从另一个终端停止所有登记批次：

```bash
make stop
```

停止命令会请求正常退出并清理所属子进程，没有运行服务或重复停止时正常返回。身份校验、超时终止和过期登记的处理见 [停止与故障清理](../architecture/local-development.md#停止与故障清理)。

每次启动都是独立批次。例如先运行 `make platform`，再运行 `make dev-bg`，后者会拒绝且原平台 API 继续运行。不同服务可分别启动；`make stop` 会停止所有批次。完整的冲突与并发启停规则见 [批次登记与并发控制](../architecture/local-development.md#批次登记与并发控制)。

端口冲突时，按错误提示自行处理占用者后重新启动。后台发生故障时，查看对应批次的 `coordinator.log` 和 `state.json`；批次清理机制见 [停止与故障清理](../architecture/local-development.md#停止与故障清理)。

## 质量检查

测试分类、执行范围和结果判定遵循 [测试规范](../conventions/testing.md)。

```bash
make check
```

`make check-backend` 执行全部单元测试、快速集成测试和契约测试，通过 `postgresql`、`slow` 标记排除专用 PostgreSQL/Redis 并发测试与进程生命周期测试。`make check` 还执行前端测试及其余质量检查。

数据库和管理员接口集成测试使用独立临时 PostgreSQL 实例及每用例独立数据库。普通用例从本轮已迁移模板克隆数据库；迁移与结构一致性专项仍从空库执行真实迁移。普通业务的账号准备使用独立账号与真实会话，认证、密码和相关审计专项保留完整初始化流程，具体机制见[后端测试运行准备](../architecture/test-runtime.md)。快速集成测试同样需要 `initdb`、`postgres` 和 `pg_ctl` 在 PATH 中。合并前执行完整测试：

```bash
make test-full
```

完整测试需要 `initdb`、`postgres`、`pg_ctl`、`pg_dump`、`pg_restore`、`redis-server` 在 PATH 中，以及已安装的前端依赖；其中备份工具用于支付发布恢复验证。测试会创建独立的临时实例、随机端口和测试数据库，完成后关闭并清理所属资源，无需先启动应用服务或手动迁移、seed。JUnit 报告写入 `build/test-results/backend.xml`、`build/test-results/admin-web.xml` 和 `build/test-results/miniapp.xml`，CI 应保留三份报告和失败日志。

按模块、文件或用例运行时，在 `services/backend/` 下选择具体路径。例如：

```bash
uv run pytest tests/integration/api/property/test_onboarding.py --require-all-tests
uv run pytest tests/unit/core/test_admin_sessions.py::test_idle_session_expires --require-all-tests
APP_RUN_POSTGRESQL_TESTS=1 uv run pytest tests/integration/postgresql --require-all-tests
uv run pytest tests/integration/dev --require-all-tests --durations=20
```

测试分类和 `postgresql`、`slow` 标记按目录自动设置。直接运行 pytest 时，未启用 `APP_RUN_POSTGRESQL_TESTS=1` 的专用 PostgreSQL/Redis 测试会给出原因并跳过；显式启用后依赖缺失会失败。上述 Make 测试入口的后端检查均启用 `--require-all-tests`，选中测试出现跳过或预期失败时返回非零，未收集到测试沿用 pytest 的非零退出码。`make test-full` 还检查三份 JUnit 报告，拒绝空报告、跳过、失败及错误记录。

任一检查失败返回非零。也可使用上表中的单项检查或构建命令。

契约测试会调用现有 `pnpm api:bundle`，确保使用最新 OpenAPI 文件。安装依赖及前端开发、检查和构建入口会自动生成本地类型；契约变更后也可执行 `pnpm api:generate-types` 刷新 IDE，再运行两端类型检查确认消费者兼容。提交契约和必要源码，生成声明由 Git 忽略。生成规则、API 设计与错误处理约定见 [API 规范](../api/conventions.md)。

### 账单支付专项验证

在 `services/backend/` 下执行支付相关单元、API、数据库、迁移和 Worker 回归：

```bash
APP_RUN_POSTGRESQL_TESTS=1 uv run --no-sync pytest \
  tests/unit/domain/payments \
  tests/unit/integrations/wechatpay \
  tests/unit/repositories/payments \
  tests/integration/api/payments \
  tests/integration/postgresql/payments \
  tests/integration/migrations/test_payment_schema.py \
  tests/integration/runtime/test_payment_worker.py \
  tests/integration/runtime/test_payment_worker_composition.py \
  --require-all-tests
```

上述范围包括以下两项，也可单独执行：

```bash
APP_RUN_POSTGRESQL_TESTS=1 uv run --no-sync pytest \
  tests/integration/api/payments/test_miniapp_controller.py \
  tests/integration/postgresql/payments/test_release_readiness.py \
  --require-all-tests
```

- `test_miniapp_controller.py`：编译实际小程序控制器，通过本地 HTTP 访问居民 API 与隔离 PostgreSQL，验证创建响应丢失后的原请求恢复、取消或未知结果、可靠关单及解绑后历史读取；微信 SDK、登录和渠道交互使用替身。
- `test_release_readiness.py`：验证关闭新单后已有订单的查询、通知、入账、分账、解冻及核对，并实际执行 `pg_dump`／`pg_restore` 到另一个全新临时数据库，核实账务与不可变保护。

支付测试使用测试密码学材料和渠道替身，不要求真实商户凭据，不调用真实资金渠道。专项测试不替代完整工程门禁；前端、契约及完整回归仍执行 `make check` 和 `make test-full`。小程序 WXML/WXSS 原生编译按[小程序构建与运行](#小程序构建与运行)单独执行，不包含在上述两个 Make 目标中。

本地测试、原生编译、真机交互和真实渠道资金验证分别判定，不能相互替代。既有验收记录见[支付实施证据](../plans/payment/bill-payments-evidence.md)，真实渠道及发布操作的前置条件见[发布与恢复准备](../plans/payment/bill-payments-release.md)。
