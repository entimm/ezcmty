# 测试服务器基础环境操作指南

本指南用于维护[测试服务器基础环境](../architecture/deployment.md#测试服务器基础环境)。系统使用 Ubuntu 26.04 LTS，原生运行 Nginx、PostgreSQL 18 和 Redis，Python 使用 3.14，依赖管理使用 uv。

已归档的项目配置及服务器目标、权限和生效检查见[配置索引](../../deploy/staging/README.md)，本指南维护组件操作与恢复流程。

基础环境维护不包含业务库与业务账号创建、数据库迁移、seed、应用发布或支付操作。域名、TLS 证书、四个 API 和 Worker 在应用发布阶段配置；支付发布条件见[账单支付发布与恢复准备](../plans/payment/bill-payments-release.md)。

## 访问与操作前检查

在已配置 SSH 别名的操作机连接：

```bash
ssh xcmty
sudo -v
```

连接信息和凭据由操作机 SSH 配置及服务器访问控制维护，不写入仓库。服务维护通过 sudo 执行，应用运行账号不用于 SSH 登录。

安装或调整组件前，先核对系统、资源、已有组件和监听范围：

```bash
cat /etc/os-release
uname -m
free -h
df -hT /
swapon --show
sudo ss -lntup
systemctl --failed --no-pager
pg_lsclusters
sudo ufw status numbered
```

同时检查目标目录是否已存在、服务是否已有配置或数据。复用现有 2GB swap，不覆盖 swap 文件或重复追加 `/etc/fstab`。不要仅因组件版本不同就重装服务、重建数据库集群或执行全系统升级。既有失败服务超出本次维护范围时，单独记录并安排处理。

## 账号与目录

运行账号为 `appsvc`，使用非登录 shell，不授予 sudo 权限。系统服务沿用发行版的专用账号与数据目录。

| 路径                                             | 用途         | 权限边界                                                                              |
| ------------------------------------------------ | ------------ | ------------------------------------------------------------------------------------- |
| `/srv/xcmty/` 及 `releases/` 子目录 | 后续应用版本 | `root:appsvc`，目录权限 `750`；静态托管时另行授予 `www-data` 必要读取权限 |
| `/etc/xcmty/` | 受控应用配置 | `root:appsvc`，目录权限 `750`；密钥文件按需限制，不向其他用户开放 |
| `/var/lib/xcmty/` | 应用运行数据 | `appsvc:appsvc`，目录权限 `750` |
| `/var/backups/xcmty/` | 本机临时备份 | `root:root`，目录权限 `700`，不向运行账号授权 |

检查账号和目录：

```bash
getent passwd appsvc
id appsvc
sudo -l -U appsvc
sudo stat -c '%U:%G %a %n' /srv/xcmty/releases \
  /etc/xcmty /var/lib/xcmty \
  /var/backups/xcmty
```

目录存在不代表已部署应用。本机备份不能替代异地备份；应用发布时另行配置业务数据库备份及恢复验证，要求见[部署约定](../architecture/deployment.md#单机部署)。

## 组件安装与更新

优先使用发行版源提供的 PostgreSQL 18、Redis、Nginx 和 Python 3.14，变更前检查候选版本及影响范围。Python 可执行文件与系统 `/usr/bin/python3` 的管理方式保持一致，不用应用安装覆盖系统 Python。

```bash
apt-cache policy postgresql-18 postgresql-client-18 redis-server nginx python3.14 python3.14-venv
python3.14 --version
psql --version
redis-server --version
nginx -v
uv --version
```

uv 使用[官方 PyPI 发布](https://pypi.org/project/uv/)的固定版本 Linux x86_64 wheel。维护步骤为：

1. 从官方 PyPI 版本 JSON 元数据选择服务器架构对应的 wheel，取得文件地址及 `digests.sha256`，下载后实际计算 SHA-256 并比较；校验失败立即停止。
2. 使用 Python 3.14 在 `/opt/uv/<版本>/` 创建独立 venv，将已校验的 wheel 安装到该环境，不向系统 Python 安装包。
3. 备份现有链接，将 `/usr/local/bin/uv`、`/usr/local/bin/uvx` 指向对应 venv 的可执行文件，检查版本、目标路径和权限。若目标已存在且不是本流程管理的链接，先确认归属，不直接覆盖。
4. 更新失败时恢复原链接；确认新版本可用前保留原安装目录，不删除仍被使用的环境。

不使用浮动的 `latest` 地址，不执行未经检查的远程脚本。具体补丁版本和维护结果记录在交付记录中，不作为本指南的固定内容。

服务器无法直连下载源时，可在操作机下载已固定版本的官方 wheel，校验后通过 SSH 传入；服务器安装前再次核对同一 SHA-256，不通过临时更换软件源修改项目锁文件。

跨用户验证 uv 时，先切换到运行账号可访问的目录，避免继承运维用户的私有工作目录：

```bash
sudo -u appsvc sh -c \
  'cd /var/lib/xcmty && /usr/local/bin/uv python find --system --no-managed-python 3.14'
```

应用发布时，systemd 同样需要设置运行账号可访问的 `WorkingDirectory`。

## 配置维护与恢复

修改前，将受影响文件连同属主和权限备份到 `/var/backups/xcmty/` 下独立的维护目录；备份目录权限为 `700`。保留原文件是否存在的信息，使用新增片段时避免覆盖同名的其他配置。

优先修改服务支持的独立配置片段。调整 PostgreSQL 或 Redis 的参数前，确认活动配置路径及实际服务实例；不要根据默认路径覆盖整份配置。项目参数以归档片段为准，按服务器资源预算维护，不在指南重复数值：

| 组件       | 项目配置来源                                                                       | 维护约束                                           |
| ---------- | ---------------------------------------------------------------------------------- | -------------------------------------------------- |
| PostgreSQL | [xcmty.conf](../../deploy/staging/postgresql/xcmty.conf) | 核对活动集群及实际参数，不覆盖集群主配置           |
| Redis      | [xcmty.conf](../../deploy/staging/redis/xcmty.conf)      | 确认主配置加载项目 include，检查回环监听及有效参数 |
| journald   | systemd 日志配置片段，沿用服务器受控配置                                           | 持久日志上限 `256M`；应用使用 journal              |

Nginx 日志沿用发行版的 logrotate 配置。Redis 达到内存上限会拒绝新增写入，应监测使用量，不能将 `noeviction` 误判为会自动释放旧会话。应用发布前结合实际进程数、数据库连接池和负载重新核对资源预算。

修改后按以下顺序处理：

1. 检查配置语法或有效参数。Nginx 先执行 `sudo nginx -t`。
2. 仅重载或重启受影响的服务，确认服务状态及本机连接。
3. 再次检查监听、磁盘、内存和系统失败服务，确认未影响 SSH。
4. 验证失败时恢复本次变更及原权限，重新检查后恢复服务；不覆盖其他维护产生的配置。

服务与日志检查：

```bash
systemctl status nginx redis-server postgresql --no-pager
systemctl is-enabled nginx redis-server postgresql
pg_lsclusters
sudo journalctl -u nginx -u redis-server --since '-15 min' --no-pager
```

PostgreSQL 的 `postgresql.service` 是汇总入口，不能只根据其 `active (exited)` 判断数据库可用。结合 `pg_lsclusters` 检查实际集群单元；例如默认集群对应 `postgresql@18-main.service`，集群名不同则替换为实际名称。

## 本机连接与入口验证

PostgreSQL 和 Redis 仅监听回环地址。用本机检查证明服务可用，不创建业务库或写入测试数据：

```bash
pg_isready -h 127.0.0.1 -p 5432
sudo -u postgres psql -X -d postgres -c 'SELECT version();'
sudo -u postgres psql -X -d postgres -c 'SHOW listen_addresses;'
redis-cli -h 127.0.0.1 ping
redis-cli -h 127.0.0.1 CONFIG GET bind protected-mode maxmemory maxmemory-policy
sudo ss -lntup
```

PostgreSQL 的版本、UTF8、时区和连接约定以[数据库规范](../database/conventions.md)为准。本阶段 PostgreSQL 使用系统管理连接验证；业务连接凭据在后续发布时创建和注入。

Nginx 的默认 HTTP 站点返回 `404`，不暴露默认欢迎页、目录索引或应用文件。修改默认站点前先确认没有已有业务，并保留原配置。验收包括配置检查和未知 Host 的实际响应：

```bash
sudo nginx -t
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H 'Host: unconfigured.invalid' http://127.0.0.1/
```

响应应为 `404`。预留 HTTPS 防火墙入口不代表已配置证书或监听 `443`；基础环境验收不据此声明 HTTPS 或业务接口可用。

## 防火墙与 SSH 连通性

UFW 默认拒绝入站、允许出站，放行 TCP `22`、`80`、`443`。变更前同时核对当前 SSH 连接的服务器端口与实际监听；若 SSH 使用其他端口，也必须保留。PostgreSQL、Redis 和 API 的回环监听不直接向公网开放；可选 Nginx IP 端口按[发布指南](staging-release.md#ip-与端口-https-入口)单独核对。云安全组由云平台单独检查，UFW 不能替代它。

首次启用 UFW 或修改 SSH 规则时，保持当前会话，先放行实际 SSH 端口，再启用或调整规则。从操作机另开新连接验证：

```bash
ssh -o ControlMaster=no -o ControlPath=none xcmty 'true'
```

新连接成功后才能结束原会话或收紧旧规则。检查 `sudo ufw status numbered` 和 `sudo ss -lntup`，确认 IPv4、IPv6 都没有数据库或 Redis 的公网监听。防火墙验证失败时，在原会话中恢复本次规则，不执行清空所有既有规则的操作。
