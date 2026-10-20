# 测试环境应用发布操作指南

本指南落实[测试环境应用发布约定](../architecture/deployment.md#测试环境应用发布)。基础组件维护见[基础环境指南](staging-environment.md)，支付开放条件见[账单支付发布与恢复准备](../plans/payment/bill-payments-release.md)。

项目配置源、服务器目标路径、权限及生效检查统一维护在[配置索引](../../deploy/staging/README.md)，本指南维护发布与恢复流程。

## 版本与取码

使用 `ssh xcmty` 登录运维账号。`ssh -T git@github-deploy` 使用服务器已有部署密钥验证 GitHub 身份；GitHub 返回成功认证文字但退出码为 `1` 属于预期。访问仓库时使用 `git@github-deploy:entimm/xcmty.git`，固定实际分支与提交 SHA，不将操作机未推送的改动混入版本。

取码前核验 GitHub 主机密钥；不关闭严格主机校验，不复制私钥。网络受限时可建立临时 SSH 回环转发，覆盖连接目标但保留 `HostKeyAlias=github.com`、部署密钥和严格主机校验。转发仅用于本次取码，完成后关闭；临时网络地址不写入永久 SSH 配置。

源码工作副本位于运维账号目录，运行账号不访问该目录或其 SSH 密钥。每次发布使用 `/srv/community-platform/releases/<UTC时间>-<短SHA>/`，包含 `backend/`、`admin-web/` 和无敏感信息的 `release.json`；`/srv/community-platform/current` 指向活动版本。

## 构建与依赖

按[测试规范](../conventions/testing.md#分级执行与结果判定)完成发布回归，保留日志与 JUnit 结果。复用其他提交的检查证据前，应证明被检部分的完整 Git tree 相同；有差异的部分单独对目标提交验证。

后端发布内容保留 `src/`、`pyproject.toml`、`uv.lock`、`alembic.ini` 和完整 `migrations/`，排除 `.env`、`.git`、`.dev/`、`devtools/`、测试、测试密钥和开发依赖。使用 Python 3.14 在最终版本路径建立 `.venv`，不复制或移动操作机的虚拟环境。

不能在线安装时，在操作机按锁文件准备 Linux x86_64、CPython 3.14 可用的运行 wheels。每个依赖校验锁文件 SHA-256，导出的 requirements 保留版本及哈希；传输后再次核对清单，以 `--no-index`、`--find-links`、`--require-hashes` 离线安装，再安装对应提交的项目 wheel。项目 wheel 来自已核验源码，单独记录 SHA-256。不要为镜像站改写项目锁文件。

管理后台在操作机或 CI 构建。先用测试默认配置执行前端检查，再仅对最终构建设置域名变量：

```bash
UMI_APP_PLATFORM_HOST=platform.xcmty.site \
UMI_APP_PROPERTY_HOST=property.xcmty.site \
pnpm --filter admin-web build
```

变量只填写 hostname。将对应版本的 `dist/` 发布到 `admin-web/`，校验产物哈希。Nginx 仅获得版本父目录的必要遍历权限及静态产物读取权限，不加入应用账号组，不获得后端、环境文件或部署密钥的读取权限。

启用 IP 与端口入口后，后续每次前端发布同时准备域名通用、平台 IP、物业 IP 三份产物，使用同一提交及锁定依赖，逐份校验哈希；两份 IP 产物的变量、独立版本目录和切换方式见[后台根路径静态产物](#后台根路径静态产物)。

## 配置、数据库与迁移

`/etc/community-platform/staging.env` 保存运行配置，`migration.env` 保存迁移配置，均为 `root:root 600`。systemd 的 PID 1 读取 `EnvironmentFile` 后降权启动进程，应用账号无需直接读取配置文件。敏感值不出现在命令参数、日志、发布清单或 Git 中。

字段分别参考[运行环境模板](../../deploy/staging/env/staging.env.example)和[迁移环境模板](../../deploy/staging/env/migration.env.example)，填入实际受控值后使用，不复制占位符上线。

数据库为 `community_platform`。`community_platform_migrator` 拥有数据库及业务 schema；`community_platform_runtime` 仅有连接、schema 使用及业务表 DML 权限，不具备 DDL 或迁移角色成员资格。首次只在空库执行已有 Alembic 迁移，不使用 seed 或 reset 工具。

在服务器选择待发布的实际目录后，通过独立受控任务执行迁移：

```bash
TASK_RELEASE=/srv/community-platform/releases/<UTC时间>-<短SHA>
sudo systemd-run --wait --pipe --collect \
  --unit=community-platform-migrate \
  -p User=community-platform -p Group=community-platform \
  -p EnvironmentFile=/etc/community-platform/migration.env \
  -p Environment=PYTHONDONTWRITEBYTECODE=1 \
  --working-directory="$TASK_RELEASE/backend" \
  "$TASK_RELEASE/backend/.venv/bin/python" -m alembic upgrade head
```

迁移前核对唯一 head；已有业务库先备份并完成独立恢复验证。迁移完成后用管理连接核对实际 `alembic_version`，撤销运行角色对该表的默认 DML 授权。检查业务表授权、运行角色无 DDL 权限及数据库角色成员关系，不只检查端口或 `/readyz`。

应用使用 `APP_ENV=staging`。可信 Origin 仅填写经授权的实际 HTTPS 后台来源，域名和可选 IP 入口均使用完整 scheme、hostname 与实际端口；Cookie 路径分别为 `/api/platform` 和 `/api/property`。没有渠道配置及独立支付开放授权时，`APP_PAYMENT_NEW_ORDERS_ENABLED=false`。

## 服务与首次管理员

systemd 管理以下五个单元，直接执行活动版本虚拟环境中的 Python，不在启动时执行依赖安装或数据库迁移。

| 单元后缀   | 运行入口                                      | 本机端口 |
| ---------- | --------------------------------------------- | -------- |
| `platform` | `backend_app.runtimes.platform_admin_api:app` | `8001`   |
| `property` | `backend_app.runtimes.property_admin_api:app` | `8002`   |
| `resident` | `backend_app.runtimes.resident_api:app`       | `8003`   |
| `webhook`  | `backend_app.runtimes.webhook:app`            | `8004`   |
| `worker`   | `python -m backend_app.runtimes.worker`       | 无       |

完整单元名为 `community-platform-<后缀>.service`。四个 API 各一个 Uvicorn worker，仅监听 `127.0.0.1`，只信任来自回环代理的转发头。服务使用 `community-platform` 账号、只读发布文件、私有临时目录与 `NoNewPrivileges`；停止等待允许 Worker 完成 SIGTERM 清理，单进程内存上限为 512MB。

切换版本后检查：

```bash
sudo systemctl status 'community-platform-*.service' --no-pager
sudo journalctl -u community-platform-worker --since '-10 min' --no-pager
curl -fsS http://127.0.0.1:8001/readyz
curl -fsS http://127.0.0.1:8002/readyz
curl -fsS http://127.0.0.1:8003/readyz
curl -fsS http://127.0.0.1:8004/readyz
```

就绪响应须分别属于正确运行端且 PostgreSQL、Redis 均为 `ok`；Worker 须记录 `worker_ready scheduler=running task_handlers=9`，并检查周期任务错误、待处理任务及重启次数。四个就绪接口不替代迁移版本检查。

首次管理员通过现有 `init-platform-admin` CLI 初始化，登录名为 `bootstrap`，首次登录必须修改密码。随机初始凭据只保存到服务器 `/etc/community-platform/bootstrap-admin.json`，权限 `600`；授权运维人员在自己的终端通过 `ssh xcmty 'sudo cat /etc/community-platform/bootstrap-admin.json'` 获取，不将结果贴入聊天或仓库。已有管理员时不重复初始化或覆盖密码。初始化任务使用运行角色和 systemd credential 注入，不把密码置于参数或日志。

## 域名、HTTPS 与验证

四个域名映射到服务器公网 IPv4：`platform.xcmty.site`、`property.xcmty.site`、`resident.xcmty.site`、`webhook.xcmty.site`。DNS 尚未生效时仅提供 ACME challenge 和其他路径 `404`，不声称页面或 HTTPS 已上线。域名入口的云安全组及 UFW 需要允许 `80/443`；数据库、Redis 和 API 的回环监听不直接暴露公网。可选 IP 入口按[独立端口规则](#ip-与端口-https-入口)放行 Nginx，不改变后端监听。IPv6 可达性未确认时不添加 AAAA。

DNS、公网 HTTP 和 ACME challenge 验证通过后签发正式证书。平台域只将 `/api/platform/` 代理到 8001，物业域只将 `/api/property/` 代理到 8002，均移除前缀；其他 API 前缀返回 `404`。居民域的 `/api/resident/` 转发到 8003 并移除前缀，回调域保留 `/webhooks/payments/wechatpay/` 路径转发到 8004。

签发与续期均要求服务器能通过 HTTPS 访问 ACME 服务。临时受限 CONNECT 代理可用于维护时的出站恢复，必须保留证书校验、仅监听回环地址并在操作结束后关闭；它不提供长期自动续期保障。签发后设置 Certbot 续期成功时的 Nginx 配置检查及 reload hook，并实际检查本次证书、部署 hook 和公网证书结果。公网 80 未放通时，先修复云入口，不重复提交失败订单。

云防火墙已放通而 HTTP-01 仍被证书机构报告连接超时时，应保留真实错误，区分操作机可达与证书机构可达。可改用四个明确域名的 DNS-01，统一收集全部 TXT 校验记录，核对公共 DNS 后再提交验证。手动 DNS 校验需要维护人员配合续期；未配置 DNS 自动化或恢复可用的 HTTP 校验链路前，不宣称证书能够无人值守续期。

证书使用 Certbot 的 `community-platform` lineage，Nginx 引用 `/etc/letsencrypt/live/community-platform/fullchain.pem` 和 `privkey.pem`，私钥仅 root 可读。查看证书状态使用 `sudo /opt/community-platform-certbot/bin/certbot certificates`，同时从公网核验实际提供的证书。续期成功 hook 必须核对 `RENEWED_LINEAGE`，只对该 lineage 执行 `nginx -t`，成功后重载 Nginx；临时 DNS hook、代理地址和 `/run` 文件不保留在续期配置中。

日常续期使用下述 DNSPod 自动流程。手动 DNS 仅用于应急：先确认服务器可访问 ACME HTTPS，再在交互终端执行以下命令，按本次提示更新 TXT，确认权威及公共 DNS 可查后继续。旧 TXT 不能代替本次校验值。应急命令可能改写续期参数，结束后须恢复 DNSPod authenticator 并重新通过非交互演练。

```bash
sudo certbot certonly --manual --preferred-challenges dns \
  --cert-name community-platform \
  -d platform.xcmty.site -d property.xcmty.site \
  -d resident.xcmty.site -d webhook.xcmty.site
```

直连不可用时，维护人员须重新建立仅允许 ACME 目标的临时 CONNECT 代理及 SSH 回环转发。通道可用后，在服务器对本次命令显式注入代理，例如将上述 `sudo certbot` 替换为 `sudo env HTTPS_PROXY=http://127.0.0.1:19445 certbot`；端口必须对应本次实际服务器回环监听。sudo 默认不保留操作账号的代理环境，不能只在登录终端设置变量。操作完成后关闭代理与转发，不把临时地址写入长期配置。

仍处于手动 DNS 状态时，由维护人员设置提醒，至少提前 30 天安排人工续期；续期后核对 Nginx 重载结果和公网实际提供的证书到期时间。Certbot 定时器对没有自动 DNS hook 的手动证书不提供无人值守续期。已切换 DNSPod 自动验证后，沿用单一 Certbot 定时器；未满足自动化条件时，不将 `renew --dry-run` 或自动续期描述为通过。

后台页面支持 SPA 回退；缺失静态资源返回 `404`，不能回退为 HTML。HTML 不做长期缓存，带内容哈希的资源可长期缓存。拒绝隐藏文件和非预期 Host。保留原始 Origin 供后端 CSRF 校验，Cookie 不关闭 Secure，不用明文登录绕过证书阻塞。

最终验收分别覆盖本机、实际公网和浏览器：有效证书、HTTP 跳转保留路径与查询参数、静态资源、前端登录页、正确端就绪、跨端 API 拒绝、未授权访问、可信与不可信 Origin。微信合法域名、小程序上传、渠道密钥和真实资金验证另行执行，不因网站上线而视为完成。

### 准备 DNSPod 自动验证凭据

HTTP challenge 入口不可用时，可通过 DNS API 自动添加和清理 TXT。该方式仍要求服务器能够独立连接 ACME 生产与 staging HTTPS，不能替代出站网络修复。`certbot-dns-tencentcloud` 插件使用腾讯云 CAM 子用户 `SecretId` / `SecretKey`，不同于旧版 DNSPod ID / Token。

1. 使用域名所属主账号打开[访问管理](https://console.cloud.tencent.com/cam/overview)，在策略管理中创建自定义策略，选择 JSON 编辑方式。
2. 复制以下策略，替换域拥有者主账号 UIN 和 `xcmty.site` 的数字 Domain ID。UIN 可在控制台账号菜单查看，Domain ID 位于[域名解析设置](https://console.cloud.tencent.com/cns/detail/xcmty.site/settings)的域名信息区域。
3. 在用户列表新建专用子用户，如 `xcmty-cert-renewal`，仅启用编程访问，关联该自定义策略，创建子用户 API 密钥。不要选择管理员或 DNSPod 全权限策略。
4. 在自己的终端保存密钥到服务器受控 INI，填写后仅核对权限和字段是否齐全，不输出密钥值。

```json
{
  "version": "2.0",
  "statement": [
    {
      "effect": "allow",
      "action": [
        "dnspod:DescribeRecordList",
        "dnspod:CreateRecord",
        "dnspod:DeleteRecord"
      ],
      "resource": ["qcs::dnspod::uin/<主账号UIN>:domain/<DomainId>"]
    }
  ]
}
```

该权限限制到整个 `xcmty.site` 域，仍允许创建、删除域内其他记录，不能宣称仅有四条 challenge TXT 的记录级权限。插件正常调用无需 `DescribeDomainList` 或 `DescribeDomain`；Domain ID 由域管理员预先取得，不必授予续期密钥额外查询权限。权限定义见 [DNSPod 域资源表](https://docs.dnspod.cn/dns/cam-resource-type/)。

服务器文件 `/etc/community-platform/dnspod-credentials.ini` 的字段格式见[DNSPod 凭据模板](../../deploy/staging/env/dnspod-credentials.ini.example)，所有者 `root:root`、权限 `600`，真实值不进入仓库或聊天。

在已有受控模板的服务器上，通过交互终端编辑：

```bash
ssh -t xcmty 'sudo nano /etc/community-platform/dnspod-credentials.ini'
```

nano 中按 `Ctrl+O`、回车保存，按 `Ctrl+X` 退出。密钥由域管理员自行填写，代理不通过浏览器创建密钥，也不读取密钥值用于聊天交付。

安装插件时固定版本并验证与服务器 Python / Certbot 的兼容性，完整指定 credentials 文件，不使用环境变量凭据模式；插件来源见 [certbot-dns-tencentcloud](https://github.com/frefreak/certbot-dns-tencentcloud)。续期成功后，仅按本次返回的记录 ID 清理 challenge，不批量删除已有 TXT。切换 authenticator 前先备份现有 renewal 配置，在 staging 中完成非交互续期及限定 deploy hook 演练，成功后核对持久配置与唯一生效的定时任务；失败保留现有生产证书和 Nginx 配置。

### DNSPod 自动续期运行环境与切换

DNSPod 续期使用独立的 `/opt/community-platform-certbot/bin/certbot`，不复用后端虚拟环境，也不修改系统 Python。Python 使用 3.14，完整依赖版本及 wheel SHA-256 以[域名依赖锁](../../deploy/staging/certbot/domain/certbot-requirements.txt)为准，保留离线包与来源记录。离线安装后执行依赖检查、原生扩展与 CSR/JWS 检查、插件发现和不联网的凭据解析检查。这些检查不替代真实 DNS 与 ACME 验证。

每次保存或轮换凭据后，先在受控脚本中校验所有者、权限及 INI：只含上述两个字段，值为非空字符串且无占位符。解析异常只输出失败和错误类型，不输出异常文本、原行或堆栈。直接省略插件的 `dns-tencentcloud-debug` 参数，并核对全局及 renewal 配置没有该项；字符串 `False` 会被此插件当作真值。Certbot 日志目录及备份只允许 root 访问，不将原始日志上传或贴入聊天。

确认服务器独立连接生产和 staging ACME HTTPS，完成受限 DNS API 增删及权威 TXT 传播检查后，以非交互方式更新既有 lineage：

```bash
sudo /opt/community-platform-certbot/bin/certbot reconfigure -n \
  --cert-name community-platform \
  --authenticator dns-tencentcloud \
  --dns-tencentcloud-credentials /etc/community-platform/dnspod-credentials.ini \
  --dns-tencentcloud-propagation-seconds 120 \
  --run-deploy-hooks
```

`reconfigure` 通过 staging 测试后才保存续期配置。`--run-deploy-hooks` 用当前有效证书验证既有限定 hook，不将 staging 证书安装到线上。验证本次 TXT 清理且原记录保留，核对持久配置的 authenticator、凭据绝对路径、传播等待值及生产 ACME server。Certbot 的成功退出不能证明 deploy hook 成功；须检查本次时间窗的 Nginx 配置检查及 systemd journal 重载成功事件。独立公网证书与页面另外核验，不能用服务器访问自身公网 IP 的结果替代。

仅在 ACME 连接、DNS 验证及限定 deploy hook 演练均成功后，使用归档的[域名 Certbot drop-in](../../deploy/staging/systemd/10-community-platform-certbot.conf)配置现有 `certbot.service`，服务器目标路径见配置索引。

执行 `systemctl daemon-reload` 后核对实际 `ExecStart`，启动一次 `certbot.service` 验证真实 systemd 入口，检查 `Result=success`、`ExecMainStatus=0`。该服务为 oneshot，完成后 inactive 正常；证书未到续期时间时，本次服务启动不替代 staging 演练。域名 lineage 沿用现有 `certbot.timer` 及随机延迟，不为同一 lineage 增加第二个 timer 或 cron；系统包自带 cron 在 systemd 主机上应跳过。独立 IP lineage 使用下节专用运行环境与 timer。后续域名证书状态检查使用 `sudo /opt/community-platform-certbot/bin/certbot certificates`；复核演练使用同一路径的 `renew --cert-name community-platform --dry-run --run-deploy-hooks`。timer 为 active、插件安装成功或 DNS API 成功，都不代表续期演练通过。

升级前备份 renewal 配置和服务 drop-in，保留原运行环境、离线包及哈希清单。新环境在新的最终绝对路径重建并验证，不能移动已有虚拟环境后直接使用；切换失败时恢复原兼容环境路径及配置。仅指回缺少 DNSPod 插件的系统 Certbot 不构成自动续期恢复。密钥轮换先验证新凭据及 staging 续期，再吊销旧密钥。

## IP 与端口 HTTPS 入口

入口、监听和应用边界以[部署设计](../architecture/deployment.md#测试环境-ip-与端口-https-入口)为准。平台和物业分别使用独立 IP 静态产物，从 `https://150.158.19.40:8001/` 和 `https://150.158.19.40:8002/` 进入现有无前缀页面路由。IP 前端发布保持后端 `current` 与域名静态产物原状；域名证书继续使用既有 Certbot 4.0 / DNSPod、`community-platform` lineage 和 `certbot.timer`。

### 后台根路径静态产物

从选定发布提交的干净源码按锁文件构建，排除操作机未提交改动和本地环境文件干扰。每次构建同时显式设置 `UMI_APP_PLATFORM_HOST`、`UMI_APP_PROPERTY_HOST`，取值如下；不能在同一构建中把两项都设为 IP，因为入口选择只读取 hostname。

| 产物     | `UMI_APP_PLATFORM_HOST` | `UMI_APP_PROPERTY_HOST` | 发布目录                         |
| -------- | ----------------------- | ----------------------- | -------------------------------- |
| 域名通用 | `platform.xcmty.site`   | `property.xcmty.site`   | 对应应用 release 的 `admin-web/` |
| 平台 IP  | `150.158.19.40`         | `property.xcmty.site`   | 独立 IP release 的 `platform/`   |
| 物业 IP  | `platform.xcmty.site`   | `150.158.19.40`         | 独立 IP release 的 `property/`   |

首次为已部署提交补齐 IP 产物时，沿用该提交的域名产物及已核验哈希，只新建两份 IP 产物；后续常规前端发布同步准备三份产物。

两份 IP 构建逐次保存各自 `dist/`，避免后一轮覆盖前一轮；清单记录完整提交 SHA、两项变量和各产物 SHA-256，传输后再核验。发布目录为 `/srv/community-platform/releases/<UTC时间>-<短SHA>-ip-admin-web/`，包含完整的 `platform/` 与 `property/`。Nginx 仅取得父目录遍历及静态文件读取权限。

独立软链接 `/srv/community-platform/ip-admin-web` 指向该完整版本目录。8001 的 server root 为 `/srv/community-platform/ip-admin-web/platform`，8002 为 `/srv/community-platform/ip-admin-web/property`；共用静态 snippet 不固定到域名产物目录。根路径、登录页和业务深链均按各自产物的无前缀路由回退到 `index.html`，API 继续分别使用 `/api/platform/`、`/api/property/`，Cookie、CSRF、可信 Origin 和端口绑定保持既定规则。

旧页面地址的迁移响应统一为 `302`，附 `Cache-Control: no-store`，按以下顺序处理：

1. 平台端的 `/platform`、`/platform/` 和物业端的 `/property`、`/property/` 跳转到 `/?_ip_entry=clean`；原 query 非空时以 `&` 追加保留。固定迁移参数只用于旧精确根路径，以避开此前 `/` 的永久重定向缓存键并防止循环；新 `/` 直接返回 `200` SPA，不额外添加 query。
2. 平台 `/platform/property/companies`、`/platform/property/communities` 及其子路径优先按现有 `sitePath` 映射到 `/companies`、`/communities`，保留后续路径和 query；其他所属端旧深链按域名逻辑去除 `/platform` 或 `/property` 页面前缀，保留 query。
3. 另一端的页面前缀返回 `404`，API 前缀不参与页面迁移。不发送 `Clear-Site-Data`，不清除 Cookie 或浏览器 storage。

切换前核对两个子目录、哈希、页面路由和资源完整性，记录原软链接目标及相关 Nginx 配置，再原子切换单一 IP 软链接；Nginx 配置变更须先 `nginx -t` 再 reload。后续前端发布同步构建三份产物，IP 产物成对切换，域名产物继续遵循应用发布流程。

IP 前端回退独立进行：已有 IP 产物版本时恢复上一完整产物对的软链接；首次从共享静态目录切换时，还需恢复原静态 root 和页面路由配置。随后核对静态资源、页面深链和所属 API，不切换后端 `current`、不修改域名产物、数据库、Origin、Cookie 或证书续期任务。版本目录保留供核验，不覆盖现用目录内容。

### 部署文件映射

IP 配置按 Nginx、systemd 和 Certbot 分类归档到 `deploy/staging/`；源文件、服务器目标、权限与验证入口见[唯一配置索引](../../deploy/staging/README.md)。先启用 challenge，生产证书存在后再启用 TLS 站点，具体续期与验收要求见下文。

### 监听、路由与配置准备

1. 核对 `150.158.19.40` 的 NAT 目标为本机 `10.0.0.2`，检查四个目标网卡端口、回环 API、Nginx 完整配置和现有防火墙。备份本次涉及的 Nginx 配置、受控环境文件、服务与防火墙规则，并记录权限及恢复命令；备份不得对普通账号开放。
2. Nginx 四个 TLS listener 分别使用 `listen 10.0.0.2:8001 bind ssl`、`listen 10.0.0.2:8002 bind ssl`、`listen 10.0.0.2:8010 bind ssl`、`listen 10.0.0.2:8020 bind ssl`。网卡地址限定监听范围，`bind` 强制 Nginx 为该地址与端口单独执行 `bind()`，保留 `127.0.0.1:8001/8002` 给已有后端；同时检查没有占用同端口的通配监听。不要将未配置于网卡的公网 NAT 地址写入 `listen`，不要将后端改为公网监听。
3. 平台和物业分别使用对应独立静态 root，从 `/` 提供无前缀页面路由和 SPA 深链；各端 API 仅代理本端，其他 API 返回 `404`。缺失静态资源返回 `404`，拒绝隐藏文件和非预期 Host；HTML 使用 `no-cache`，其他静态资源缓存 3600 秒，API 和 Webhook 响应使用 `no-store`。IP Host 的 80 端口仅提供 `/.well-known/acme-challenge/`，其他路径返回 `404`，不提供 HTTP 登录。
4. 平台增加精确 Origin `https://150.158.19.40:8001`，物业增加 `https://150.158.19.40:8002`，保留已有域名 Origin，代理不改写来源；配置修改后重启使用该环境文件的应用单元。保持 staging、Cookie 安全属性、非重叠 Path 和支付开关。四个云端与主机 TCP 放行规则只针对 Nginx 入口；公网 80 持续用于证书校验。云端规则由具备权限的人员在云平台核对，服务器 UFW 或本机请求成功不能证明云端已放行。

TLS 站点设置 `absolute_redirect off`，API 前缀补斜杠使用相对 `308`，保留查询参数，由浏览器保留当前 IP 与端口；旧页面迁移使用上节的 `302 / no-store`，根路径直接提供对应后台页面。向 TLS 端口误发 HTTP 时，`497` 转为显式包含同一 IP、同一端口及 `$request_uri` 的 HTTPS `308`；绝对跳转不能仅拼接不含端口的 `$host`，否则会落到 443。验收应检查根路径页面及跳转的实际 `Location`，覆盖查询参数、旧深链和 API 补斜杠。

### 独立 IP 证书运行环境

IP 字面量必须使用 IP SAN，不能复用仅含四域 DNS SAN 的证书。独立客户端使用支持 `--ip-address` 的 Certbot 5.8 / ACME 5.8，完整 17 个依赖版本及 Linux wheel SHA-256 以[固定依赖锁](../../deploy/staging/certbot/ip/certbot-requirements.txt)为准，不在指南另存哈希。该锁针对 CPython 3.14.4、Linux x86_64、glibc ≥ 2.40，仅使用 wheel；其他目标环境须重新准备兼容依赖并核验，不直接套用。在最终绝对路径安装，离线安装使用 `--no-index`、`--find-links`、`--require-hashes` 并限制为 wheel，逐包核验哈希，执行依赖检查及原生 CSR / IP SAN 检查，不覆盖域名 Certbot 或应用虚拟环境，不修改后端 `uv.lock`。官方参数与 profile 依据见 [Certbot 使用指南](https://eff-certbot.readthedocs.io/en/stable/using.html)及 [Let’s Encrypt Profiles](https://letsencrypt.org/docs/profiles/)。

| 用途                   | 路径或名称                                                                      |
| ---------------------- | ------------------------------------------------------------------------------- |
| IP 客户端              | `/opt/community-platform-certbot-ip/bin/certbot`                                |
| 独立配置 / 工作 / 日志 | `/etc/letsencrypt-ip` / `/var/lib/letsencrypt-ip` / `/var/log/letsencrypt-ip`   |
| HTTP-01 webroot        | `/var/www/community-platform-acme-ip`                                           |
| 独立 lineage           | `community-platform-ip`                                                         |
| Nginx 证书 / 私钥      | `/etc/letsencrypt-ip/live/community-platform-ip/fullchain.pem` / `privkey.pem`  |
| 限定成功 hook          | `/usr/local/sbin/community-platform-ip-cert-deploy`                             |
| systemd 服务 / timer   | `community-platform-certbot-ip.service` / `community-platform-certbot-ip.timer` |

配置、工作目录和日志只允许 root 访问，私钥仅 root 可读。webroot 仅存放公开 challenge，不放置密钥、环境文件或日志；Nginx 仅获得 challenge 读取权限。所有 IP 客户端调用显式传入三个隔离目录，不让 Certbot 4.0 扫描 IP renewal 配置。

先验证服务器可独立通过 HTTPS 连接生产及 staging ACME，校验系统时间与信任链，不依赖操作机在线、临时代理或永久 CA IP 绑定。在 IP Host 的公网 80 challenge 链路通过独立外部访问验证后，使用本次独立临时 config / work / logs 目录完成 CA staging 的真实 HTTP-01 验证，不加载 staging 证书到线上。CA 报告连接失败时保留真实错误，修复入口后再重试，不以操作机 curl 成功替代 CA 验证。

生产签发使用固定客户端、`certonly --webroot --webroot-path /var/www/community-platform-acme-ip --ip-address 150.158.19.40 --required-profile shortlived --cert-name community-platform-ip`，并显式指定上述生产隔离目录。ACME 账号的条款确认和联系信息按实际受控方式配置，不放入发布包。`--required-profile shortlived` 使不支持该 profile 时明确失败，不静默退回其他 profile。核对生产 ACME server、IP SAN、完整链和 160 小时有效期后，才允许 Nginx 引用生产证书。

### 自动续期与日常维护

`community-platform-ip` 的持久 renewal 配置须保留 webroot、IP 标识、生产 ACME server、`shortlived` profile 及限定 deploy hook；续期调用始终显式使用上述三个隔离目录。hook 仅接受 `RENEWED_LINEAGE=/etc/letsencrypt-ip/live/community-platform-ip`，其他 lineage 不处理。匹配后先创建 root 专用、权限 `600` 的 `/var/lib/letsencrypt-ip/deploy-failed` 标记，再执行 `nginx -t` 和 reload；两步全部成功才清除标记，失败返回非零并保留标记及日志。hook 由 root 拥有且不可由应用账号修改，不读取或输出私钥。

复制可执行脚本后，须将它注册到 IP 实例的持久 deploy 目录；仅复制到 `/usr/local/sbin/` 不会自动运行。首次安装执行：

```bash
sudo install -d -o root -g root -m 700 /etc/letsencrypt-ip/renewal-hooks/deploy
sudo ln -s /usr/local/sbin/community-platform-ip-cert-deploy \
  /etc/letsencrypt-ip/renewal-hooks/deploy/50-community-platform-ip
sudo readlink -f /etc/letsencrypt-ip/renewal-hooks/deploy/50-community-platform-ip
```

链接已存在时先核对目标，不强制覆盖。Certbot 从该隔离目录发现 hook，不再重复添加命令行 `--deploy-hook`，也不注册到域名实例的目录。

专用 [oneshot 服务](../../deploy/staging/systemd/community-platform-certbot-ip.service)以 root 运行独立客户端，仅续期 IP lineage，显式传入 config / work / logs 目录。专用 [timer](../../deploy/staging/systemd/community-platform-certbot-ip.timer) 按服务器时区每日 00:00、12:00 触发，最多增加 30 分钟随机延迟；`Persistent=true` 在错过触发后补跑。续期时机由 Certbot 判定，不周期性强制签发；不为 IP lineage 另设 cron，不改动域名续期服务或 timer。

正式 unit 保留 `ProtectSystem=strict` 等隔离，通过 `ReadWritePaths=-/run/nginx.pid` 限定允许 Nginx 配置检查访问 PID 文件；不要为 hook 直接关闭 sandbox。服务在 Certbot 返回成功后，先通过 `ExecStartPost=/usr/bin/test ! -e /var/lib/letsencrypt-ip/deploy-failed` 检查 hook 失败标记，再使用 `openssl x509 -checkend 172800` 检查本机 `/etc/letsencrypt-ip/live/community-platform-ip/cert.pem` 剩余有效期是否超过 48 小时。任一检查失败均使服务失败，并记录到 systemd journal；即使 Certbot 对 hook 失败返回 `0`，残留标记仍会阻止服务报告成功。上述检查不验证公网实际证书、SAN、完整信任链或 Nginx 已加载新证书。

运维日常检查服务退出状态、journal 和 hook 重载事件，续期失败或本机证书剩余不足 48 小时立即处理；公网证书按下节另行人工验收及巡检，不将本机自动到期检查描述为公网监控。短期证书不能沿用域名证书提前 30 天人工提醒的维护方式。

```bash
sudo systemctl status community-platform-certbot-ip.service community-platform-certbot-ip.timer --no-pager
sudo systemctl list-timers community-platform-certbot-ip.timer --no-pager
sudo journalctl -u community-platform-certbot-ip.service --since '-24 hours' --no-pager
sudo journalctl -t community-platform-ip-cert-deploy --since '-24 hours' --no-pager
sudo journalctl -u nginx.service --since '-24 hours' --no-pager
```

四个 TLS listener 引用生产证书且本机验收通过后，在正式 unit 的 sandbox 内执行真实非交互 staging 续期及限定 hook 演练。使用 `sudo systemctl edit --runtime community-platform-certbot-ip.service` 创建本次临时 drop-in，仅清空并覆盖 `ExecStart`，保留原 unit 的 sandbox、写入路径和两项 `ExecStartPost`：

```ini
[Service]
ExecStart=
ExecStart=/opt/community-platform-certbot-ip/bin/certbot renew --non-interactive --cert-name community-platform-ip --config-dir /etc/letsencrypt-ip --work-dir /var/lib/letsencrypt-ip --logs-dir /var/log/letsencrypt-ip --dry-run --run-deploy-hooks --no-random-sleep-on-renew
```

创建前记录已有 runtime drop-in；`daemon-reload` 后检查有效配置，再通过 systemd 启动本次演练。确认真实 HTTP-01、Nginx 检查和 reload 事件、失败标记不存在及两项补充检查通过；普通 root CLI 演练无法证明正式 unit 的文件系统权限和 hook 可用。演练不得用 staging 证书替换生产证书。完成后仅撤销本次测试 drop-in，恢复原 ExecStart 并 `daemon-reload`，启动一次正式 oneshot，检查 `Result=success`、`ExecMainStatus=0` 和 timer 下一次触发时间；未到续期时间的空跑不能替代上述真实演练。状态查看及证书枚举仍使用同一 IP 客户端与三个隔离目录，原始日志仅在服务器受控查看。

演练通过且已恢复正式 ExecStart 后，显式启用专用 timer，并验证正式服务入口：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now community-platform-certbot-ip.timer
sudo systemctl start community-platform-certbot-ip.service
```

核对 timer 为 `enabled`、`active` 且存在下一次触发时间；只复制 unit、运行 `daemon-reload` 或启动 oneshot 均不能激活定时续期。

失败标记存在时，先查看专用服务、hook 标签和 Nginx 日志，修复配置或 sandbox 写入权限；更改 unit 后执行 `daemon-reload`。然后用当前有效 lineage 手动重试限定 hook：

```bash
sudo env RENEWED_LINEAGE=/etc/letsencrypt-ip/live/community-platform-ip \
  /usr/local/sbin/community-platform-ip-cert-deploy
```

确认 hook 成功清除标记后，执行 `sudo systemctl restart community-platform-certbot-ip.service` 并复核 oneshot 状态和日志；标记不手动删除，以免掩盖重载失败。修复后的正式 unit 仍须完成上述 sandbox 内真实 dry-run，确认本次配置检查、reload 与两项补充检查均通过，再恢复正常定时续期。未到续期时间的 oneshot 成功或标记不存在，均不能证明本次执行过 hook；须保留对应时间窗的 hook 和 reload 证据。

### 分层验收与回退

- 本机：`nginx -t` 通过，四个 listener 只绑定网卡地址，四个 API 仍在 `127.0.0.1:8001–8004`；原域名入口、Worker、PostgreSQL 和 Redis 正常。四端 `/readyz` 在回环检查，平台、物业和居民可再通过各自 API 前缀验证对应运行端；Webhook 保持仅回环暴露就绪接口。
- 独立公网：从服务器之外验证四个 IP HTTPS 端口，使用默认 CA 信任完成 IP 主机名校验，不使用 `-k`；核对 IP SAN、完整证书链及到期时间，验证云端和主机防火墙。服务器访问自身公网地址不能替代此项。
- Webhook 路由：使用 `GET https://150.158.19.40:8020/webhooks/payments/wechatpay/payment-success`，检查 `405` 及 `Allow: POST`，验证已到达对应接口且不提交支付载荷。
- 浏览器与授权边界：验证两个端口 `/` 选择正确后台，无前缀登录页及业务深链、菜单链接与登录后返回地址、静态资源、真实登录及后续会话、Secure / HttpOnly / SameSite 与 Cookie Path、正确和错误 Origin、跨端 API 和非预期 Host 拒绝。旧精确根与深链验证 `302 / no-store`、query 保留、特殊 `sitePath`、另一端前缀拒绝；带既有根路径 `308` 缓存的浏览器须能经固定迁移参数抵达新入口且不循环，正常新 `/` 不附加参数。使用已有授权测试账号或会话，不读取或重置管理员密码；无法完成真实登录时明确保留该验收项。
- 续期：正式 unit sandbox 内的真实 staging HTTP-01、非交互 renew、限定 hook、失败标记与到期检查、systemd 实际入口和 timer 触发时间均通过；确认生产证书仍在线，域名 Certbot / DNSPod 运行环境和调度保持正常。普通 root CLI、timer active 或一次无需续期的成功退出不单独构成验收。

仅回退 IP 前端时按[独立静态产物回退](#后台根路径静态产物)处理。撤除整个 IP 入口时，先恢复本次修改的 Nginx 配置，检查并重载，确认 IP listener 和证书引用已撤除，再停止并禁用 IP timer 及对应服务；Nginx 恢复失败时保留当前证书续期保障。随后恢复本次变更的 Origin 配置并重启受影响应用，移除本次新增的四个端口放行规则，验证原域名入口与回环服务；公网 80 若为既有入口则保留。变更前备份相关配置，每次 `nginx -t` 成功才 reload，应用配置修改后验证服务就绪。证书仍有效时保留其受控文件和日志用于恢复，不删除既有 lineage、不吊销域名证书、不回退数据库或应用版本，不让仍在线的 IP 入口失去续期保障。

居民和 Webhook 的 IP 入口只代表接口联调能力，不证明微信合法域名、回调配置或真实支付已通过；IP 端口与域名 443 入口分别验收。

## 备份与恢复

使用系统管理连接将 `pg_dump -Fc` 输出到 `/var/backups/community-platform/` 下 `root:root 600` 文件。备份后实际恢复到本次专用临时数据库，检查迁移版本及表数据；不能只用 `pg_restore --list` 代替恢复验证。清理仅针对本次创建的验证库，禁止对业务库执行测试清空或回退迁移。

本机备份不具备异地容灾能力。定期备份、容量监测与异地复制按实际测试数据保留需求配置。回退应用前先检查数据库兼容，停止相关任务进程，原子切换 `current` 并重新验证；不通过删除支付事实或自动降级数据库恢复。
