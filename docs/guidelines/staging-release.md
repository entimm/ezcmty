# 测试环境应用发布操作指南

本指南落实[测试环境应用发布约定](../architecture/deployment.md#测试环境应用发布)。基础组件维护见[基础环境指南](staging-environment.md)，支付开放条件见[账单支付发布与恢复准备](../plans/payment/bill-payments-release.md)。

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

## 配置、数据库与迁移

`/etc/community-platform/staging.env` 保存运行配置，`migration.env` 保存迁移配置，均为 `root:root 600`。systemd 的 PID 1 读取 `EnvironmentFile` 后降权启动进程，应用账号无需直接读取配置文件。敏感值不出现在命令参数、日志、发布清单或 Git 中。

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

应用使用 `APP_ENV=staging`。可信 Origin 仅填写两个实际 HTTPS 后台来源，Cookie 路径分别为 `/api/platform` 和 `/api/property`。没有渠道配置及独立支付开放授权时，`APP_PAYMENT_NEW_ORDERS_ENABLED=false`。

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

四个域名映射到服务器公网 IPv4：`platform.xcmty.site`、`property.xcmty.site`、`resident.xcmty.site`、`webhook.xcmty.site`。DNS 尚未生效时仅提供 ACME challenge 和其他路径 `404`，不声称页面或 HTTPS 已上线。云安全组及 UFW 需要允许 `80/443`；不开放数据库、Redis、API 监听端口。IPv6 可达性未确认时不添加 AAAA。

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

服务器文件 `/etc/community-platform/dnspod-credentials.ini` 内容格式如下，所有者 `root:root`、权限 `600`，不进入仓库或聊天：

```ini
dns_tencentcloud_secret_id = <SecretId>
dns_tencentcloud_secret_key = <SecretKey>
```

在已有受控模板的服务器上，通过交互终端编辑：

```bash
ssh -t xcmty 'sudo nano /etc/community-platform/dnspod-credentials.ini'
```

nano 中按 `Ctrl+O`、回车保存，按 `Ctrl+X` 退出。密钥由域管理员自行填写，代理不通过浏览器创建密钥，也不读取密钥值用于聊天交付。

安装插件时固定版本并验证与服务器 Python / Certbot 的兼容性，完整指定 credentials 文件，不使用环境变量凭据模式；插件来源见 [certbot-dns-tencentcloud](https://github.com/frefreak/certbot-dns-tencentcloud)。续期成功后，仅按本次返回的记录 ID 清理 challenge，不批量删除已有 TXT。切换 authenticator 前先备份现有 renewal 配置，在 staging 中完成非交互续期及限定 deploy hook 演练，成功后核对持久配置与唯一生效的定时任务；失败保留现有生产证书和 Nginx 配置。

### DNSPod 自动续期运行环境与切换

DNSPod 续期使用独立的 `/opt/community-platform-certbot/bin/certbot`，不复用后端虚拟环境，也不修改系统 Python。使用 Python 3.14、`certbot==4.0.0`、`acme==4.0.0`、`certbot-dns-tencentcloud==2.1.1`；所有传递依赖固定版本及 wheel SHA256，保留离线包、依赖清单与来源记录。离线安装后执行依赖检查、原生扩展与 CSR/JWS 检查、插件发现和不联网的凭据解析检查。这些检查不替代真实 DNS 与 ACME 验证。

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

仅在 ACME 连接、DNS 验证及限定 deploy hook 演练均成功后，为现有 `certbot.service` 添加 drop-in，清空原 `ExecStart` 后设为：

```ini
[Service]
ExecStart=
ExecStart=/opt/community-platform-certbot/bin/certbot -q renew --no-random-sleep-on-renew
```

执行 `systemctl daemon-reload` 后核对实际 `ExecStart`，启动一次 `certbot.service` 验证真实 systemd 入口，检查 `Result=success`、`ExecMainStatus=0`。该服务为 oneshot，完成后 inactive 正常；证书未到续期时间时，本次服务启动不替代 staging 演练。沿用现有 `certbot.timer` 及随机延迟，不增加第二个 timer 或 cron；系统包自带 cron 在 systemd 主机上应跳过。后续状态检查使用 `sudo /opt/community-platform-certbot/bin/certbot certificates`；复核演练使用同一路径的 `renew --cert-name community-platform --dry-run --run-deploy-hooks`。timer 为 active、插件安装成功或 DNS API 成功，都不代表续期演练通过。

升级前备份 renewal 配置和服务 drop-in，保留原运行环境、离线包及哈希清单。新环境在新的最终绝对路径重建并验证，不能移动已有虚拟环境后直接使用；切换失败时恢复原兼容环境路径及配置。仅指回缺少 DNSPod 插件的系统 Certbot 不构成自动续期恢复。密钥轮换先验证新凭据及 staging 续期，再吊销旧密钥。

## 备份与恢复

使用系统管理连接将 `pg_dump -Fc` 输出到 `/var/backups/community-platform/` 下 `root:root 600` 文件。备份后实际恢复到本次专用临时数据库，检查迁移版本及表数据；不能只用 `pg_restore --list` 代替恢复验证。清理仅针对本次创建的验证库，禁止对业务库执行测试清空或回退迁移。

本机备份不具备异地容灾能力。定期备份、容量监测与异地复制按实际测试数据保留需求配置。回退应用前先检查数据库兼容，停止相关任务进程，原子切换 `current` 并重新验证；不通过删除支付事实或自动降级数据库恢复。
