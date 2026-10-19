# 测试环境证书自动续期实施计划

范围：为 `community-platform` 的四域证书配置无需操作机在线的自动续期，沿用 Certbot、现有证书路径及限定 Nginx 重载 hook。用户已授权自动续期配置；不变更业务服务、现有 DNS 业务记录或支付设置。

依据：[部署约定](../../architecture/deployment.md#测试环境应用发布)、[发布指南](../../guidelines/staging-release.md#域名https-与验证)。

- [x] 核对现有 lineage、timer、hook、Nginx challenge 入口及服务状态，备份将要修改的配置。
- [x] 诊断服务器到生产及测试 ACME 的出站，核对 DNS、时间、CA、代理、路由及本机规则，区分本机与外部网络限制。
- [x] 修复稳定 ACME 出站：用户按腾讯云建议更换公网 IP 后，生产与 staging 接口均直连成功，正常验证 TLS，无代理或永久 IP 绑定；实际 CA 演练通过。
- [x] 选择并验证自动域名校验：HTTP webroot 公网被拦截，采用域限定 DNSPod API；实际验证新增 TXT、权威解析及按返回 ID 清理，原记录保留。
- [x] 安装固定版本的独立 Certbot / DNSPod 运行环境，完成服务器原生扩展、依赖、插件发现、无网络 smoke 与真实 INI 加载检查。
- [x] 配置持久 authenticator、凭据权限及续期任务；保留限定 lineage 的 Nginx 检查和重载 hook，避免重复定时任务。
- [x] 完成实际无人交互续期演练，验证 DNS challenge 清理、hook、证书路径、私钥隔离及服务器应用可用性。
- [ ] 完成来自独立外部网络的四域公网 HTTPS 验收；服务器经自身公网 IP 的成功结果不能替代该项。
- [x] 更新维护指南、执行格式与引用检查并交付；明确独立公网复核尚未通过，不将 timer 启用等同于自动续期成功。

自动续期验收条件：服务器独立执行非交互续期演练成功；不依赖操作机在线或人工 TXT；生产证书、限定 Nginx hook 与五个应用服务正常，敏感凭据仅 root 可读；失败时保留有效证书并按备份恢复配置。公网入口另外验收，未通过时如实报告。

完成结论：更换公网 IP 后，生产及 staging ACME 均可由服务器直接访问并正常校验 TLS。独立 Certbot 的 DNSPod authenticator 已持久保存，真实非交互 staging 演练通过，自动 TXT 创建与清理保持原有记录不变。Nginx 配置检查及重载均通过，正式证书和私钥保持原状。

现有 `certbot.service` 已切换至独立运行环境，实际服务启动退出成功；现有 `certbot.timer` 保持 enabled / active，未新增重复调度。五个应用、四个就绪接口及数据库依赖均正常。日常续期无需人工 TXT 或操作机在线，维护和回退步骤见[发布指南](../../guidelines/staging-release.md#dnspod-自动续期运行环境与切换)。

独立公网验收仍未完成：服务器本机和经自身公网 IP 的 HTTPS 均通过，但操作机 curl 与浏览器连接失败，具体外部路径原因尚未定位。该限制不影响已通过的 DNS-01 续期演练，不能据服务器自身请求宣称独立公网验收通过。

详细诊断、备份位置和执行证据保留在操作机 `build/deployment-verification/certificate-auto-renewal-20261020.json`、`ip-change-public-health-20261020.json` 及服务器受控备份，不随文档提交。凭据只保存在服务器 root 可读文件中，未写入仓库或交付输出。
