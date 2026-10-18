# 账单支付实施证据

本文件记录本次实施映射、检查结果及未满足条件，不另行定义业务、数据或接口规则。任务状态以 [实施计划](bill-payments.md) 为准；设计与契约沿用计划列出的权威来源。检查日志保留在未纳入版本控制的 `.dev/payment/`。

## 阶段 0 核查范围

核查日期：2026-10-19。工作目录：`/Users/xsavorai/Dev/git-worktree/xlife2-bill-payments`。已阅读项目 `AGENTS.md`、开发及文档规范、测试及数据库规范、支付业务与数据设计、既有账单设计、API 规范及 OpenAPI、代码组织、后端、后台、小程序及本地开发约定。

初始只读核查确认：OpenAPI 为 `0.12.0`，运行时错误目录为 `0.9.0`；Worker 与本地启动器依赖占位 `task_handlers=0` 标记。不能通过手改生成目录或运行环境版本掩盖差异；生成目录由 P0-04 更新，Worker 及启动器由 P2-07 更新。

## 接口实施与验证映射

下列操作来自四个支付 OpenAPI 模块，共 36 个契约操作；同一管理读取操作分别检查平台及物业运行入口。路径、输入、权限、响应和错误仍以 OpenAPI 为唯一依据。

| 运行入口   | 操作 ID                                         | 实施任务     | 验证归属                                   |
| ---------- | ----------------------------------------------- | ------------ | ------------------------------------------ |
| 平台       | `listCompanyMerchantBindings`                   | P3-02        | 配置 API 集成、完整契约、P7-02 页面        |
| 平台       | `createCompanyMerchantBinding`                  | P3-02、P3-03 | 配置创建幂等、令牌、审计及权限集成         |
| 平台       | `getCompanyPaymentConfiguration`                | P3-02        | 完整可用性原因、权限、契约                 |
| 平台       | `replaceCompanyActiveMerchantBinding`           | P3-02、P3-03 | 初始化、切换、往返令牌、事务外渠道核验     |
| 平台       | `listCompanyProfitSharingRuleVersions`          | P3-02        | 历史规则及配置权限、契约                   |
| 平台       | `createCompanyProfitSharingRuleVersion`         | P3-02、P3-03 | 不可变聚合、同键重放、比例及配置竞争       |
| 平台       | `getCompanyProfitSharingRuleVersion`            | P3-02        | 确切版本、范围、契约                       |
| 物业       | `listCurrentCompanyMerchantBindings`            | P3-04        | 本公司历史及权限、契约                     |
| 物业       | `getCurrentCompanyPaymentConfiguration`         | P3-04        | 本公司配置投影、无写能力                   |
| 物业       | `listCurrentCompanyProfitSharingRuleVersions`   | P3-04        | 本公司历史、范围、契约                     |
| 物业       | `getCurrentCompanyProfitSharingRuleVersion`     | P3-04        | 本公司确切版本、越界不存在                 |
| 居民       | `listResidentHouseBills`                        | P3-05        | 当前房屋完整授权、分页及总数隔离           |
| 居民       | `getResidentBill`                               | P3-05        | 当前房屋授权、占用及可用操作投影           |
| 居民       | `listResidentBillSettlementEntries`             | P3-05        | 独立分页、他人及管理员文本脱敏             |
| 居民       | `listResidentPaymentOrders`                     | P4-02        | 本人范围、解绑后可查、固定摘要             |
| 居民       | `createResidentPaymentOrder`                    | P4-03        | 原键恢复、全部余款、版本、占用及任务原子性 |
| 居民       | `getResidentPaymentOrder`                       | P4-02        | 本人授权、固定摘要、普通 GET 无副作用      |
| 居民       | `createResidentClientPaymentParameters`         | P4-04、P4-06 | 当前授权、原订单、禁止缓存及凭证保护       |
| 居民       | `createResidentPaymentRefresh`                  | P4-04        | 原单查询任务合并、202 语义                 |
| 居民       | `createResidentPaymentClosure`                  | P4-04        | 本人原单关闭、关闭与成功竞争               |
| 平台、物业 | `listManagedPaymentOrders`                      | P4-11        | 分端权限、公司记录/总数/汇总一致过滤       |
| 平台、物业 | `getManagedPaymentOrder`                        | P4-11        | 收款与入账区别、分端投影及关联账单         |
| 平台、物业 | `listManagedProfitSharingOrders`                | P5-07        | 本公司范围、应分与执行区别、契约           |
| 平台、物业 | `getManagedProfitSharingOrder`                  | P5-07        | 逐接收方成功/失败/未知及只读投影           |
| 平台、物业 | `listManagedUnfreezeOrders`                     | P5-07        | 本公司范围、未知金额及契约                 |
| 平台、物业 | `getManagedUnfreezeOrder`                       | P5-07        | 独立执行、实际金额及 no_remaining 语义     |
| 平台、物业 | `listManagedReconciliationRuns`                 | P6-04        | 平台完整与物业局部汇总、分页               |
| 平台、物业 | `getManagedReconciliationRun`                   | P6-04        | 本公司投影、无平台完整账户证据泄漏         |
| 平台、物业 | `listManagedReconciliationDiscrepancies`        | P6-04        | 差异范围、稳定键、总数隔离                 |
| 平台、物业 | `getManagedReconciliationDiscrepancy`           | P6-04、P6-05 | 当前判定及历史依据、物业受限投影           |
| 平台       | `recoverManagedPaymentOrder`                    | P5-07        | 独立恢复权限、原因/任务/审计原子提交       |
| 平台       | `recheckManagedReconciliationRun`               | P6-07        | 原批次任务合并、权限与审计                 |
| 平台       | `recoverManagedReconciliationDiscrepancy`       | P6-07        | 进入原能力、无第二资金成功路径             |
| 平台       | `recordManagedReconciliationExternalResolution` | P6-08        | 双权限、令牌、并发/未知、只记处置不改资金  |
| Webhook    | `receiveWechatPayPaymentSuccess`                | P4-07        | 原文验签、去重及保存失败的渠道 ACK         |
| Webhook    | `receiveWechatPayProfitSharingNotification`     | P5-06        | 独立通知类型、到账佐证不替代整单查询       |

四个 HTTP 入口执行 `tests/contract/` 全量一致性检查，不能用空壳路由、删契约或放宽检查补齐。第五个 Worker 入口无 HTTP API，验证任务分派、周期生产、真实就绪、停止、重启及租约接管（P2-01～P2-08、P4-05、P6-02）。

## 核心不变量实施与验证映射

| 不变量与边界                                                      | 实施任务                   | 必要验证                                            |
| ----------------------------------------------------------------- | -------------------------- | --------------------------------------------------- |
| 15 张新表、2 张旧表扩展、单一迁移 head、公司复合外键              | P1-01～P1-03               | 隔离 PostgreSQL 空库及旧数据升级、Model/迁移一致    |
| 配置身份、完整规则、支付明细和应分不可变                          | P1-02、P3-02               | 直接 SQL 越界/改写/追加/删除拒绝，不只测 ORM        |
| 表注册、Harness 精确集合、seed 逐表归属                           | P1-08                      | 迁移/Harness/普通 seed 回归，不伪造真实资金任务     |
| 共享入账无身份依赖、不提交事务、不伪造管理员                      | P1-04、P1-05               | 系统操作者读取、调用者回滚、线下原有流程            |
| 同账单单占用；占用不增加账单版本                                  | P1-02、P4-03               | 多连接创建竞争、占用前后版本不变                    |
| 线下收款/纠错/撤销/作废在账单锁内拒绝占用，线上收款不可线下冲正   | P1-07                      | API 与直接 SQL 保护、多连接线上/线下竞争            |
| 当前全部余款、预期版本、付款人键幂等；订单/明细/占用/任务原子提交 | P4-03                      | 同键同输入/异输入、余额变化、事务故障注入           |
| 固定上级资源→账单→支付锁序；资金操作只锁支付父记录                | P1-05、P4-08、P5-04        | 真实 PostgreSQL 竞争，无逆向等待路径                |
| 渠道调用四段提交、网络期间无事务、可信证据先持久                  | P2-05、P2-06               | HTTP 替身检查事务状态、业务回滚后证据保留           |
| 请求签名、响应/通知验签、原文解密与条件敏感字段加密               | P2-03、P2-04               | 真实 cryptography 运算；坏签名/结构/身份隔离        |
| 通知可靠保存及任务同事务；渠道 ACK 不代表入账                     | P4-07                      | 重复通知、保存失败、原文签名及渠道响应              |
| `confirmation.py` 唯一收款确认、通知与查单共用                    | P4-08                      | 通知/查单竞争、重复/乱序、共享入账唯一性            |
| 支付成功、全部账务、应分/首笔执行及任务、原占用释放原子提交       | P4-09、P4-10               | 每步故障回滚、逐明细幂等、awaiting_posting 保留占用 |
| 应分在入账生成；按订单金额逐方 half-up；零应分直接建解冻单        | P4-09                      | 半分边界、多接收方、零比例及舍入后渠道上限          |
| 未知沿原号原参数恢复；只有可靠不可支付终态或未发送取消才释放      | P4-04、P4-10               | 超时/断网/进程中断/迟到证据、关闭与支付竞态         |
| 本人历史与当前房屋授权分开；解绑不阻止可信收款                    | P3-05、P4-02、P4-06、P4-08 | 解绑/停用前后读取、签发拒绝、真实收款入账           |
| 到期及授权失效订单周期补齐查关单，不直接清占用                    | P4-05                      | 可控时钟、停机重启、多 Worker 任务合并              |
| 商户切换与规则升级只影响新单；激活不等于 ready                    | P3-02、P3-03               | 无规则/上限未知/ratio_exceeded、原单冻结配置        |
| 配置令牌识别往返修改；重放不重激活或重发布                        | P3-03                      | 渠道核验间并发变更、旧令牌、同键持久重放            |
| SKIP LOCKED、租约及代次保护，旧执行者只可存迟到证据               | P2-01、P2-06               | 多连接领取/续租/接管、失效回写拒绝                  |
| 应分与执行分离，成功不重复、未知不另建、累计成功不超应分          | P5-01～P5-03               | 多接收方部分成功、未知原单恢复、受理次数限制        |
| 全部足额且无在途才解冻；任一解冻单永久阻止新分账                  | P5-04、P5-05               | 分账/解冻真实数据库竞争、解冻失败后屏障             |
| 解冻金额只取可信实际结果；no_remaining 不冒充分账到账             | P5-05                      | 缺失金额保持未知、资金不足不撤销居民缴费            |
| 核对按账户和业务日生产、历史绑定不遗漏、停机漏日分页补齐          | P6-01～P6-03               | 跨日、历史停用绑定、重复生产、缺文件不当零          |
| 来源先独立保存；判定快照/批次/差异/任务及 finished_at 原子完成    | P6-06                      | 下载后中断、判定回滚、旧代次不能发布部分结果        |
| 差异维度稳定去重、金额和手续费可并存、解决后再现重开              | P6-04、P6-05               | 稳定键、历次来源及处置依据保留                      |
| 恢复进入原能力；外部处置只记录差异结论且与审计原子保存            | P6-07、P6-08               | 双权限、旧令牌、核对竞争、未知响应、资金各表不变    |
| 各端 Service 不互调，普通 GET 无渠道/任务/签发副作用              | P3-04、P4-01、P4-11        | 导入边界、各运行入口契约、HTTP 调用副作用断言       |
| 物业记录/总数/汇总同范围且不取得平台完整对象                      | P3-04、P5-07、P6-04、P7-09 | 越权不存在、受限 Schema、跨公司及跨后台响应         |
| 居民原请求按 API 环境/用户隔离，SDK 成功只请求核实                | P7-03～P7-06               | 取消/双击/重开/隐藏/卸载/401/切用户/迟到响应        |
| 凭证仅内存；日志/URL/快照/恢复存储无密钥、签名、预支付凭证        | P2-05、P7-05、P7-06        | 白名单快照及导航/存储/日志断言                      |
| 前端配置冲突不覆盖、201/202/处置成功不显示资金成功                | P7-02、P7-07、P7-08        | 后台表单/未知响应/权限及纯展示测试                  |
| 停止新单后旧资金继续；发布与目标库写入必须另授权                  | P8-09～P8-12               | 隔离环境停新单恢复、迁移/备份演练及发布清单         |

Domain 单元测试验证计算与规则；应用/API 集成测试验证权限、状态、事务及脱敏；真实 PostgreSQL 测试验证行锁、约束、迁移及竞争；进程集成测试验证生命周期及接管；前端测试验证请求隔离与交互。各层按不同验证边界分工，实际渠道通过必须另有明确授权和证据。

## 本次检查记录

| 检查                             | 实际结果                                                                              | 证据                                                                     |
| -------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Node/pnpm/uv                     | 已安装：Node 24.15.0、pnpm 10.33.2、uv 0.11.8                                         | 本地命令版本核查                                                         |
| PostgreSQL/Redis 可执行文件      | `initdb`、`postgres`、`pg_ctl`、`redis-server` 在 PATH                                | 只核查存在性，未连接业务库                                               |
| 初次 `make check-frontend`       | 失败：新 worktree 还未安装 node_modules，`max` 不存在                                 | `.dev/payment/baseline-frontend.log`                                     |
| 初次 `make check-api`            | 失败：同一安装前环境缺 `redocly`                                                      | `.dev/payment/baseline-api.log`                                          |
| 安装后 `make check-frontend`     | 失败：管理端类型及 Lint 通过；153 用例中 150 通过、3 失败，后续命令因 Make 短路未执行 | `.dev/payment/baseline-frontend-installed.log`                           |
| 管理端独立生产构建               | 通过                                                                                  | `.dev/payment/baseline-admin-build.log`                                  |
| 小程序独立类型、Lint、测试       | 通过：5 文件、20 用例，无跳过                                                         | `.dev/payment/baseline-miniapp-checks.log`                               |
| 小程序独立构建及原生编译         | 通过：WXML、WXSS 均用本机微信编译器执行                                               | `.dev/payment/baseline-miniapp-build.log`、`baseline-miniapp-native.log` |
| 安装后 `make check-api`          | OpenAPI Lint、bundle 通过；契约失败：生成错误目录过期                                 | `.dev/payment/baseline-api-installed.log`                                |
| 生成目录更新后的四端契约逐一核查 | 均未通过：平台缺 21、物业缺 14、居民缺 9、Webhook 缺 2 个操作；无多暴露操作           | `.dev/payment/baseline-runtime-contracts.log`                            |

初次依赖缺失属于新 worktree 环境前置问题，不能算业务实现回归；安装后结果另记，不覆盖原始日志。四端共 46 个缺失操作归属前述 36 个支付契约操作，其中 10 个管理只读操作同时属于两端；这是契约领先实现的缺口。该次逐端核查直接调用既有 `get_operations`、`check_runtime`，未修改检查算法；因操作集合尚不一致，不能声称已验证全部已有 Schema 差异。后端基线、生成目录与密码学兼容结果由集成人补录。

管理端 3 个失败均出现在本次前端实现开始前：`property-onboarding` 找不到“启用”按钮、`house-claims` 找不到脱敏手机号、`housing` 找不到首屏房屋文本，均由 Testing Library 异步查询超时触发。现有配置已限制 `maxWorkers=2`，未配置更长的异步查询等待。针对 `house-claims` 同一用例独立诊断通过（1 通过，名称筛选未执行另外 11 个），说明失败与执行条件相关；它不能替代首轮全量失败结果，也尚不足以断定具体竞争原因。证据为 `.dev/payment/baseline-house-claims-diagnostic.log`。本次未修改无关模块或放宽等待以制造通过。

## 外部条件与执行隔离

只做材料存在性核查，未读取、复制或输出已有 `.env` 中的值。新 worktree 没有后端 `.env`；原工作目录有后端 `.env`，内容未读取，不能据此判定商户材料齐备。当前进程未设置平台 AppID、AppSecret 或小程序 AppID；支付配置模板尚未提供真实商户材料。服务商号、特约商户号、平台接收账号、签名私钥/APIv3 密钥、验签材料、HTTPS 回调及合法域名均未验证，不能标记齐备。未发起任何真实渠道请求。

隔离开发使用测试生成的密码学材料、可控时钟、HTTP/SDK 渠道替身，数据库测试复用项目每测试独立 PostgreSQL 数据库及专用临时实例；不连接已有开发、测试或生产业务数据库，不执行其迁移、seed 或业务写入。测试依赖须显式启用并拒绝必需测试跳过。不能使用实际商户调用建立接收关系、付款、分账或解冻。

仓库 `check:native` 实际默认位置为微信开发者工具的 `app.asar.unpacked/node_modules/wcc-exec`；本机 WXML/WXSS 编译均已通过，不能据最初候选路径未命中判定编译器缺失。`MINIAPP_WCC`、`MINIAPP_WCSC` 未设置。原生编译不等于真机交互或真实支付验收。真机操作、真实资金验收与部署本次未授权；这些外部条件不阻塞替身开发与隔离工程验收。准备发布及迁移方案不等于执行部署、远程推送、主线合并或目标库写入。

## 阶段 0 集成核实

- 分支 `feat/bill-payments`，工作区 `/Users/xsavorai/Dev/git-worktree/xlife2-bill-payments`，来源 `b2c85ed`；原仓库工作区干净且未改动。
- 后端基线 `make check-backend`：Ruff、格式及 mypy（211 文件）通过；pytest 为 266 通过、5 失败、133 按范围未选择，无跳过（263.51 秒）。五项失败分别为旧生成目录与四个运行端支付契约缺口，详见 `.dev/payment/baseline-backend.log`。
- P0-04 已运行 `pnpm api:generate-errors`，运行时目录现为 0.12.0；生成后完整契约仍因缺失支付实现失败，未修改检查算法。
- P0-05 将 `cryptography>=50.0.2,<51` 声明为直接运行依赖，使用 uv 更新现有锁文件。Python 3.14.4 下真实 RSA-SHA256 签名验签与 AES-256-GCM 加解密通过；不等于真实微信渠道验收。
