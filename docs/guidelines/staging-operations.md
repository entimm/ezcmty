# 测试环境运维手册

本手册面向测试服务器的日常检查、配置维护、受控发布、迁移、证书维护和故障恢复。服务器基础组件的安装、账号初始化和防火墙基线见[测试环境基础环境操作指南](staging-environment.md)；完整的应用构建、域名及 IP 入口验收见[应用发布操作指南](staging-release.md)；配置文件的服务器映射、属主和权限见[配置索引](../../deploy/staging/README.md)。

仓库中的 `deploy/staging/` 只保存配置源和脱敏模板，不代表服务器已经安装或启用这些文件。实际状态必须在服务器上通过 `systemctl`、`ss`、`nginx -t` 和本机健康检查确认。仓库当前没有自动发布工作流或制品构建脚本；部署网关只接受经过核验的发布归档，不把源码目录、操作机虚拟环境或任意压缩包直接交给服务器。

## 操作边界

- 使用 `ubuntu` 运维账号登录，保留当前 SSH 会话，另开连接验证后再结束原会话或收紧 SSH、防火墙规则。
- 应用运行账号 `appsvc`、迁移账号 `appsvc-migrator` 和构建账号 `appsvc-builder` 不用于人工登录；`deployer` 只接受固定的部署协议。
- 不在命令参数、日志、工单或聊天中输出数据库 URL、Redis 密码、DNS 凭据、Cookie、私钥或管理员初始凭据。
- 修改配置前备份本次涉及的文件；先检查语法和有效配置，再 reload 或 restart。失败时只恢复本次变更及其权限。
- 发布、迁移和回退分别执行。激活不会自动迁移数据库，不能通过删除数据、`downgrade` 或回退支付事实处理版本不兼容。
- `APP_PAYMENT_NEW_ORDERS_ENABLED` 默认保持 `false`；开放支付新单必须另行授权，并按支付发布与恢复计划完成验收。
- 不直接修改 `/srv/xcmty/current`、`/srv/xcmty/ip-admin-web` 软链接；版本切换统一使用受控部署网关。

## 账号、路径与入口

| 对象              | 当前用途                                       |
| ----------------- | ---------------------------------------------- |
| `ubuntu`          | 人工 SSH 运维和 `sudo`；无提权时只读代码和日志 |
| `appsvc`          | 五个 API / Worker 的运行账号                   |
| `appsvc-migrator` | 受控 Alembic 迁移和版本检查                    |
| `appsvc-builder`  | 发布安装时在隔离 systemd 任务中建立虚拟环境    |
| `deployer`        | 受限 SSH 部署入口，不提供 Shell、TTY 或转发    |
| `www-data`        | Nginx 静态文件读取，不应读取后端和受控配置     |

| 路径                                   | 用途                               |
| -------------------------------------- | ---------------------------------- |
| `/srv/xcmty/releases/`                 | 已安装的不可覆盖发布版本           |
| `/srv/xcmty/current`                   | 当前后端和域名静态产物软链接       |
| `/srv/xcmty/ip-admin-web`              | 当前平台、物业 IP 静态产物软链接   |
| `/srv/xcmty/.deploy/`                  | root 专用锁、封存记录和部署状态    |
| `/etc/xcmty/staging.env`               | 应用运行环境，`root:root 600`      |
| `/etc/xcmty/migration.env`             | 迁移环境，`root:root 600`          |
| `/etc/xcmty/redis-admin.env`           | Redis 管理凭据，`root:root 600`    |
| `/var/lib/xcmty/`                      | 应用运行数据                       |
| `/var/backups/xcmty/`                  | 本机临时备份，目录 `root:root 700` |
| `/usr/local/sbin/xcmty-deploy-gateway` | root 部署网关                      |
| `/usr/local/sbin/xcmty-redis`          | root-only Redis 管理 helper        |

五个 systemd 服务为 `xcmty-platform.service`、`xcmty-property.service`、`xcmty-resident.service`、`xcmty-webhook.service` 和 `xcmty-worker.service`。四个 API 只监听回环地址 `127.0.0.1:8001`–`8004`；Worker 不监听 HTTP 端口。域名入口由 Nginx 提供，IP 联调入口使用网卡地址 `10.0.0.2:8001`、`:8002`、`:8010`、`:8020`。当前部署约定由公网 `150.158.19.40` 经 NAT 到该网卡；变更公网地址或网卡时以 Nginx、云安全组和 NAT 的实际配置为准。

## 登录和日常巡检

登录后先确认主机、权限和资源状态：

```bash
ssh xcmty
sudo -n true
hostnamectl
date -u
df -hT /
free -h
sudo ss -lntup
sudo systemctl --failed --no-pager
sudo pg_lsclusters
sudo ufw status numbered
```

查看活动版本、软链接和服务：

```bash
readlink -f /srv/xcmty/current
readlink -f /srv/xcmty/ip-admin-web
sudo systemctl status 'xcmty-*.service' --no-pager
sudo systemctl is-active xcmty-platform.service xcmty-property.service \
  xcmty-resident.service xcmty-webhook.service xcmty-worker.service
```

逐个检查四个就绪接口。响应必须为正确运行端，且 PostgreSQL、Redis 依赖均为 `ok`：

```bash
curl --fail --silent --show-error http://127.0.0.1:8001/readyz
curl --fail --silent --show-error http://127.0.0.1:8002/readyz
curl --fail --silent --show-error http://127.0.0.1:8003/readyz
curl --fail --silent --show-error http://127.0.0.1:8004/readyz
sudo journalctl -u xcmty-worker.service --since '-10 min' --no-pager
```

Worker 应出现 `worker_ready scheduler=running task_handlers=9`，同时检查持续重启、周期任务错误和积压。`/readyz` 通过不代表数据库迁移版本正确，版本必须另外核对。

## 日志和故障定位

按故障组件读取有限时间范围的日志，不复制整个环境文件或进程环境：

```bash
sudo journalctl -u xcmty-platform.service --since '-15 min' --no-pager
sudo journalctl -u xcmty-property.service --since '-15 min' --no-pager
sudo journalctl -u xcmty-resident.service --since '-15 min' --no-pager
sudo journalctl -u xcmty-webhook.service --since '-15 min' --no-pager
sudo journalctl -u xcmty-worker.service --since '-15 min' --no-pager
sudo journalctl -u nginx.service --since '-15 min' --no-pager
```

记录时间、服务、发布 ID、请求 ID、错误类型和脱敏后的响应。不要使用 `cat /etc/xcmty/*.env`、`ps eww` 或包含认证头的调试命令收集现场信息。

常见判断顺序如下：服务失败先看对应 journal、运行 UID、工作目录和版本目标；502 先看上游端口、Nginx 配置和静态软链接；Worker 异常先看最新就绪记录、任务错误和依赖状态；Redis 认证失败先核对应用使用的 ACL 身份及键前缀，不扩大权限绕过检查。

## 配置修改和服务重启

修改前建立一次性备份目录，并保留原文件是否存在的信息：

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/var/backups/xcmty/$STAMP
sudo install -d -o root -g root -m 700 "$BACKUP"
sudo cp -a --preserve=all /etc/xcmty/staging.env "$BACKUP/"
sudo stat -c '%U:%G %a %n' /etc/xcmty/staging.env
```

使用 `sudoedit` 修改受控文件，完成后再次检查属主和权限：

```bash
sudoedit /etc/xcmty/staging.env
sudo stat -c '%U:%G %a %n' /etc/xcmty/staging.env
```

`staging.env` 使用数据库角色 `xcmty_runtime`、Redis ACL 身份 `xcmty-runtime` 和数据库 `xcmty`。`migration.env` 使用独立迁移角色，数据库 URL 必须是回环 PostgreSQL 5432 地址；迁移文件不能作为应用服务的 `EnvironmentFile`。两个文件都不能包含 `xcmty-admin`、数据库管理员或其他管理凭据。

共享运行环境变更后重启全部受影响的服务：

```bash
sudo systemctl restart xcmty-platform.service xcmty-property.service \
  xcmty-resident.service xcmty-webhook.service xcmty-worker.service
```

修改 systemd 单元后先执行 `sudo systemctl daemon-reload`，再重启对应服务。修改 Nginx 前先执行 `sudo nginx -t`，通过后再执行 `sudo systemctl reload nginx`。PostgreSQL、Redis 参数必须确认实际活动集群和主配置 include 后再 reload 或 restart。

## 受控发布

发布入口由仓库中的 [`deploy/staging/bin/xcmty-deploy-gateway`](../../deploy/staging/bin/xcmty-deploy-gateway)、服务器上的 `/usr/local/sbin/xcmty-deploy-gateway` 和 [`deploy-ssh`](../../deploy/staging/ssh/deploy-ssh) 共同组成。SSH 强制命令只传递原始命令数据；`deployer` 不能执行任意 Shell、TTY、端口转发或用户配置。`seal` 只允许 root 在服务器本地调用。

### 发布归档要求

网关接收标准 USTAR 归档，大小上限为 1 GiB，展开总量上限为 2 GiB，单文件上限为 512 MiB，成员数上限为 100,000。归档必须包含以下内容：

```text
release.json
backend/
  requirements.txt
  wheels/*.whl
  alembic.ini
  migrations/env.py
admin-web/index.html
ip-admin-web/platform/index.html
ip-admin-web/property/index.html
```

`release.json` 只包含 `schema_version: 1`、发布 ID、40 位提交 SHA 和 `python_target: cp314-linux-x86_64`。依赖必须固定版本并带 SHA-256，且包含 `backend-app`。归档拒绝路径穿越、隐藏路径、重复成员、软链接、硬链接、设备文件、FIFO 和其他特殊文件。发布 ID 只能使用字母、数字、`.`、`_`、`-`，长度不超过 96。

构建机或操作机必须先完成项目规定的检查，并在传输前核对归档摘要。当前仓库不包含自动生成该归档的工作流或脚本；没有经过核验的归档时停止发布，不用手工打包源码目录替代。

### 安装、迁移和激活

常规发布通过 `deployer` 的受限 SSH 入口执行。操作机必须预先配置主机密钥和部署公钥；`ssh -T` 只调用固定协议，不提供交互 Shell。安装命令从标准输入接收归档，不能把归档路径作为网关参数：

```bash
RELEASE_ID=<release-id>
ARCHIVE=<path-to-release.tar>
DIGEST=$(sha256sum "$ARCHIVE" | awk '{print $1}')
ssh -T deployer@<staging-host> status
ssh -T deployer@<staging-host> "install $RELEASE_ID $DIGEST" < "$ARCHIVE"
ssh -T deployer@<staging-host> status
```

`install` 会校验哈希、USTAR 头、路径、元数据和依赖清单，在 root 隔离的临时文件系统中由 `appsvc-builder` 创建虚拟环境并离线安装 wheel，随后生成 root 封存记录。安装失败时不激活该版本，不删除其他版本或状态目录；保留错误输出供管理员检查，修复后使用新的发布 ID。

服务器本地管理员或受控入口故障时，才在保持 SSH 会话的情况下直接调用同一网关：

```bash
sudo /usr/local/sbin/xcmty-deploy-gateway install "$RELEASE_ID" "$DIGEST" < "$ARCHIVE"
sudo /usr/local/sbin/xcmty-deploy-gateway status
```

数据库变更必须显式执行。迁移前完成业务库备份和独立恢复验证，确认目标发布的唯一 Alembic head：

```bash
ssh -T deployer@<staging-host> "migrate $RELEASE_ID"
```

迁移由 `appsvc-migrator` 在受控 `systemd-run` 任务中执行，并读取 `/etc/xcmty/migration.env`。迁移不会切换活动版本；迁移失败时先核对事务结果和实际 head，不盲目重跑或自动降级。

数据库 head 与封存 head 一致后才激活：

```bash
ssh -T deployer@<staging-host> "activate $RELEASE_ID"
ssh -T deployer@<staging-host> status
```

`activate` 原子切换 `current` 和 `ip-admin-web`，重启五个服务并检查 `127.0.0.1:8001`–`8004` 的 `/readyz`。就绪检查失败时网关尝试恢复两个旧软链接并重启旧服务；管理员仍需复核服务、Worker、静态入口和公网入口。不要在网关外单独切换其中一个软链接。

### 回退

先记录当前版本和两个软链接目标，选择已安装、已封存且与当前数据库 head 兼容的上一版本：

```bash
readlink -f /srv/xcmty/current
readlink -f /srv/xcmty/ip-admin-web
sudo ls -1dt /srv/xcmty/releases/*
```

使用同一个 `activate` 执行整体回退。数据库 head 不匹配时网关会拒绝激活；此时由管理员评估兼容版本和恢复方案，不直接执行 `downgrade`、删除业务数据或修改支付事实。回退后重新执行四端 `/readyz`、Worker 就绪、域名入口和 IP 入口检查。

## Redis、数据库和入口检查

Redis 管理只能通过 root-only helper，凭据从 `/etc/xcmty/redis-admin.env` 注入，不出现在参数中：

```bash
sudo /usr/local/sbin/xcmty-redis PING
sudo /usr/local/sbin/xcmty-redis CONFIG GET bind protected-mode maxmemory maxmemory-policy
```

匿名连接应被拒绝；不要把 `ACL LIST`、`ACL GETUSER`、完整配置或业务键值复制到运维记录。运行身份只使用 `xcmty-runtime`，并限制在 `app:*` 键和应用所需命令。Redis 重启后重复检查认证、ACL、锁、重连和四端就绪。

PostgreSQL 和 Redis 应只监听回环地址：

```bash
pg_isready -h 127.0.0.1 -p 5432
sudo -u postgres psql -X -d postgres -c 'SHOW listen_addresses;'
sudo ss -lntup
```

Nginx 配置变更前后执行：

```bash
sudo nginx -t && sudo systemctl reload nginx
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H 'Host: unconfigured.invalid' http://127.0.0.1/
```

未知 Host 应返回 `404`。域名入口的实际 HTTPS、四个域名、API 前缀和浏览器行为按发布指南逐层验收；不能只用本机 `curl` 代替公网和浏览器检查。

## 证书巡检

域名证书使用 `xcmty` lineage 和系统 `certbot.timer`；如果已启用可选的 IP 入口，IP 证书使用独立的 `xcmty-ip` lineage 和 `xcmty-certbot-ip.timer`。先通过 `systemctl` 确认对应服务已安装并启用，再检查最近日志和剩余有效期：

```bash
sudo systemctl status certbot.timer --no-pager
sudo journalctl -u certbot.service --since '-24 hours' --no-pager
sudo /opt/xcmty-certbot/bin/certbot certificates
```

仅在 `systemctl list-unit-files xcmty-certbot-ip.service` 显示该服务已安装时，执行 IP 证书检查：

```bash
sudo systemctl status xcmty-certbot-ip.service xcmty-certbot-ip.timer --no-pager
sudo systemctl list-timers xcmty-certbot-ip.timer --no-pager
sudo journalctl -u xcmty-certbot-ip.service --since '-24 hours' --no-pager
sudo journalctl -t xcmty-ip-cert-deploy --since '-24 hours' --no-pager
sudo test ! -e /var/lib/letsencrypt-ip/deploy-failed
sudo openssl x509 -checkend 172800 -noout \
  -in /etc/letsencrypt-ip/live/xcmty-ip/cert.pem
```

续期 hook 失败时保留现有证书和 Nginx 配置，先检查 `nginx -t`、lineage、写入目录和 hook 日志。不要通过复制证书、删除失败标记或增加第二个 cron/timer 掩盖失败。

`timer` 为 active、Certbot 单次命令成功或插件已安装，都不能单独证明续期成功；必须结合本次时间窗的 service journal、hook 日志、失败标记和证书有效期判断，真实续期演练按[发布指南](staging-release.md)执行。

## 备份和恢复

配置备份放在本次独立的 `/var/backups/xcmty/<UTC时间>/`，目录为 `root:root 700`，敏感文件为 `root:root 600`。数据库备份使用管理连接生成自定义格式，并实际恢复到本次专用临时数据库验证迁移版本和数据；`pg_restore --list` 不能替代恢复验证：

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=/var/backups/xcmty/$STAMP
sudo install -d -o root -g root -m 700 "$BACKUP"
set -euo pipefail
sudo -u postgres pg_dump -Fc -d xcmty | sudo tee "$BACKUP/xcmty.dump" >/dev/null
sudo chown root:root "$BACKUP/xcmty.dump"
sudo chmod 600 "$BACKUP/xcmty.dump"
```

恢复验证只清理本次创建的临时库，不对业务库执行测试清空或回退迁移。应用回退前先确认数据库兼容；不能用删除支付事实或自动降级数据库替代恢复。

## 交付记录

每次维护至少记录 UTC 时间、操作者、发布 ID 和提交 SHA、变更前后软链接、迁移 head、服务状态、四端就绪结果、Worker 日志摘要、Nginx/证书检查结果及失败恢复动作。记录中只保留脱敏结果和请求标识，不写入密码、连接串、私钥、Cookie、ACL 哈希或完整环境文件。
