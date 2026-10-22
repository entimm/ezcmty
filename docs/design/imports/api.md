# 通用批量导入 API 设计

## 范围与契约边界

本设计定义通用导入的资源、输入输出、权限、幂等、错误和文件传输行为。产品边界见 [通用批量导入设计](overview.md)，页面状态见 [页面与交互设计](interaction.md)，持久化约束见 [数据库设计](database.md)，服务与任务边界见 [技术架构设计](architecture.md)。前端不直接访问内部表。

[OpenAPI 入口及其引用](../../../openapi/openapi.yaml) 是唯一 API 契约权威来源。[导入模块](../../../openapi/modules/imports.yaml) 定义操作、权限和状态码，请求响应模型、参数及共享错误响应分别归入 [Schema](../../../openapi/components/import-schemas.yaml)、[参数](../../../openapi/components/import-parameters.yaml) 和 [响应](../../../openapi/components/import-responses.yaml)。根契约已表达本设计，运行端尚未实现；遵循 OpenAPI First，先确定契约，再实现运行端。实施时登记已实现的领域错误并生成错误目录，提交前通过各运行端契约一致性检查，不得放宽检查以忽略未实现接口。

本轮能力不包含业务接入。未注册生产适配器时类型目录返回空数组，创建未知或不可用类型被拒绝；不发布测试导入类型，不用生产数据表构造演示能力。测试适配器只位于测试目录。

后端路径为 `/v1/...`，端入口分别为 `/api/platform/v1/...`、`/api/property/v1/...`。运行端通过 `x-runtimes` 声明 `platform_admin_api`、`property_admin_api`，后台归属不能由请求切换。字段采用 `snake_case`，标识使用项目 UUID 格式，模板版本和预览版本使用正整数，SHA-256 均为小写 64 位十六进制，不带 `sha256:` 前缀；页面模板版本显示为 `v1` 等名称。

## 公共行为

### 身份、权限与范围

所有接口校验所属后台会话；写操作复用现行 Cookie、CSRF 及会话失效规则。两端权限使用独立前缀 `platform.import`、`property.import`，以下后缀按端拼接：

| 权限后缀              | 对应操作                                     |
| --------------------- | -------------------------------------------- |
| `read`                | 历史、详情、行、问题、时间线、错误文件状态。 |
| `create`              | 类型目录、模板配置、模板下载、创建草稿。     |
| `upload`              | 上传源文件。                                 |
| `precheck`            | 重新预检。                                   |
| `execute`             | 确认执行。                                   |
| `cancel`              | 取消。                                       |
| `retry`               | 失败行重跑。                                 |
| `recover`             | 原任务核实与恢复。                           |
| `generate_error_file` | 生成错误文件。                               |
| `download`            | 下载错误文件。                               |

导入权限与适配器声明的实际业务创建权限叠加；字段读取与下载还需满足业务字段权限。类型目录只返回当前端具备上述业务能力的类型。平台端不能因为拥有导入权限而取得物业端业务写入能力，适配器不支持的后台不暴露该类型。

首期范围仅为 `company`、`community`。平台创建请求必须显式提供 `property_company_id`；物业请求不得提供该字段，公司从身份取得。`scope = {type, id}` 中公司范围的 `id` 必须等于目标公司，小区范围的 `id` 必须属于该公司。服务端生成 `scope` 名称与不可变快照，不接受任意客户端快照。房屋、账期和资源集合范围另行接入。

文件中的范围不能覆盖批次范围；不匹配产生阻断问题 `import.scope_mismatch`。解析、重新预检、确认、恢复和每个执行分块前复核权限、公司与小区状态。查询、分页总数和下载应用同一范围过滤；跨后台、跨公司或不可见资源返回 `404 resource.not_found`，已可见资源缺少操作权限返回 `403 auth.forbidden`。`next_actions` 只是提示，不能代替服务端检查。

### 成功、分页与时间

成功直接返回资源、数组或分页结果，不包装 `code/message/data`。分页统一为 `items/total/page/page_size`；`page` 默认 1、最小 1，`page_size` 默认 20、范围 1–100。时间戳为带时区 RFC 3339，响应统一 UTC `Z`；时间筛选 `created_from` 含边界、`created_before` 不含边界，两者同时存在时后者必须较晚。敏感 JSON 与文件响应均返回 `Cache-Control: no-store` 和 `X-Request-ID`。

所有对象 Schema 拒绝未声明的输入字段。标识、分页、筛选及组合不合法返回 `422 VALIDATION_ERROR`。行值对象仅接受模板字段；具体字段类型由固定模板定义，不接受任意客户端列映射。

### 请求幂等与安全重试

所有 POST 使用必填 `Idempotency-Key`，为长度 1–128、匹配 `[A-Za-z0-9_-]+` 的字符串。请求键由目标公司、后台、用户、动作作用域和键值隔离，持久化于 `import_requests`。动作作用域为 `create`，或 `source_file/precheck/confirm/cancel/retry_failed/error_file/recover:{batch_uuid}`；读取原目标批次后再确定公司，不信任请求中的身份值。

同一键、同一规范化输入返回首次成功 HTTP 状态与白名单响应体，不重复创建批次、任务或业务操作；同键不同输入返回 `409 import.idempotency_conflict`。重放前重新检查当前权限和资源范围，响应头使用本次请求标识。动作、审计、调度及首次成功响应在同一事务提交；无成功动作的校验失败不占用请求键。并发竞争失败方回滚后读取首次结果。

创建指纹只含固定类型、模板版本、服务端范围与模式；上传指纹含批次和服务端核实的源文件摘要；确认指纹包含预览版本、摘要、`apply_policy` 和 `include_warning_rows`。重预检、取消、重跑、恢复和文件生成使用各自规范化输入。请求指纹不混入服务端时间、随机任务 ID 或上传前尚不存在的文件摘要。

请求幂等与业务幂等独立。逻辑业务操作使用稳定 `operation_key`，任务接管与失败重跑复用原键；成功操作读取既有结果，未知结果先核实原操作。超时后查询批次或以原键和原输入重放；`409`、`503` 和超时本身不表示允许盲目重试。自动重试仅适用于安全读取或具备幂等保证的写入，使用有界退避；只有能够承诺等待时间才返回 `Retry-After`。

## 资源与操作

| 方法 | 路径                                                              | 成功响应                                    |
| ---- | ----------------------------------------------------------------- | ------------------------------------------- |
| GET  | `/v1/import-types`                                                | `200 ImportTypeList`。                      |
| GET  | `/v1/import-types/{type_key}/versions/{version_no}`               | `200 ImportTemplate`。                      |
| GET  | `/v1/import-types/{type_key}/versions/{version_no}/template-file` | `200` 模板文件流。                          |
| POST | `/v1/import-batches`                                              | `201 ImportBatchAction`，创建草稿。         |
| GET  | `/v1/import-batches`                                              | `200 ImportBatchPage`。                     |
| GET  | `/v1/import-batches/{batch_id}`                                   | `200 ImportBatch`。                         |
| POST | `/v1/import-batches/{batch_id}/source-file`                       | `202 ImportBatchAction`，安排解析与预检。   |
| GET  | `/v1/import-batches/{batch_id}/rows`                              | `200 ImportRowPage`。                       |
| GET  | `/v1/import-batches/{batch_id}/issues`                            | `200 ImportIssuePage`。                     |
| GET  | `/v1/import-batches/{batch_id}/events`                            | `200 ImportEventPage`，分页时间线。         |
| POST | `/v1/import-batches/{batch_id}/precheck`                          | `202 ImportBatchAction`，重新预检。         |
| POST | `/v1/import-batches/{batch_id}/confirm`                           | `202 ImportBatchAction`，安排执行。         |
| POST | `/v1/import-batches/{batch_id}/cancel`                            | `202 ImportBatchAction`，记录协作取消请求。 |
| POST | `/v1/import-batches/{batch_id}/retry-failed`                      | `201 ImportRetryResult`，新批次及预检任务。 |
| POST | `/v1/import-batches/{batch_id}/recover`                           | `202 ImportBatchAction`，核实与恢复原任务。 |
| POST | `/v1/import-batches/{batch_id}/error-file`                        | `202 ImportErrorFileAction`，独立文件任务。 |
| GET  | `/v1/import-batches/{batch_id}/artifacts/error-file`              | `200 ImportErrorFile`，生成状态。           |
| GET  | `/v1/import-batches/{batch_id}/artifacts/error-file/download`     | `200` 鉴权文件流。                          |

`type_key` 为长度 1–64、匹配 `[a-z][a-z0-9_]*` 的稳定类型标识，`version_no >= 1`；批次路径参数为 UUID。模板与源文件只允许 CSV、XLSX；模板下载通过 `format=csv|xlsx` 指定，默认 `xlsx`。具体操作都声明认证、CSRF、权限、状态码、错误媒体类型及下载响应头，不从内部表名派生额外外部接口。

## 类型与模板

`ImportTypeList = {items: ImportType[]}`，不分页。可选查询参数 `scope_type=company|community`，按范围类型、当前端、业务权限及新建可用性过滤。`ImportType` 包含 `key/name/allowed_scope_types/supported_modes/versions`；一期 `supported_modes` 只含 `create`，`versions` 包含 `version_no/config_hash/available_for_new_batches/template_downloadable/released_at/release_notes`。只返回已授权类型与版本；没有可用类型返回空 `items`。

`ImportTemplate` 包含 `key/name/version_no/config_hash/available_for_new_batches/released_at/release_notes/fields`。`fields` 按模板顺序返回：`key/label/order/required/data_type/max_length/format/enum_values/example/description/normalization_rules`。可空字段显式为 `null`，枚举值与示例使用模板允许的 JSON 标量。`data_type` 为 `string/integer/decimal/boolean/date/datetime`；规范化规则提供安全、可读说明，不向客户端开放规则执行语言。

批次固定绑定 `template_key + template_version_no + template_config_hash`；配置缺失或漂移停止写入，不能回退最新版本。停用新建不等于删除历史配置；有读取权限的历史批次仍可加载其固定模板投影。模板下载也经过授权，不暴露存储键或公开短链。

## 创建、上传及批次投影

### 创建草稿

`POST /v1/import-batches` 的 JSON 输入为：

| 字段                  | 类型与规则                     |
| --------------------- | ------------------------------ |
| `import_type`         | `type_key`。                   |
| `template_version_no` | 正整数，允许新建的版本。       |
| `property_company_id` | UUID；平台必填，物业禁止提供。 |
| `scope`               | `{type: company                | community, id: UUID}`。 |
| `mode`                | `create`。                     |

服务端检查类型及后台可用性、固定配置、业务权限、范围归属和模式，返回 `ImportBatchAction`，初始 `status=draft`、`phase=awaiting_source_file`。类型、范围、模板和模式创建后不可修改。未上传草稿在 `created_at + 24h` 失效；源文件、敏感快照统一保留到 `created_at + 30d`。

### 上传源文件

`POST .../source-file` 使用 `multipart/form-data`，唯一字段 `file` 为必填二进制；只允许草稿上传一次，已上传批次以原幂等键重放或查询，不能替换源文件。CSV 实际媒体类型为 `text/csv`，XLSX 为 `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`。文件最大 `10 MiB = 10,485,760 bytes`、最多 50,000 数据行、200 列；上传字节、解压膨胀、单元格长度和内存占用均受服务端有界限制。

服务端核实大小、实际格式、完整性和 SHA-256，拒绝宏、外部链接及不符合模板的内容。字节放在私有本地持久目录，数据库仅保存元数据。成功关联文件、登记首次响应并安排解析和预检后返回 `202 ImportBatchAction`，状态 `prechecking`，排队通过 `phase=parse_queued` 和任务 `status=ready` 表达。

同步可判定的过大、格式不支持和无效文件分别返回 `413 import.file_too_large`、`415 import.file_type_unsupported`、`422 import.file_invalid`。异步文件/行问题保存到问题资源；上传成功不表示解析完成或业务成功。

### 写响应与批次详情

所有批次 POST 返回最小 `ImportBatchAction={batch_id,status,phase,preview_version,active_task,source_artifact}`。其中任务仅含 `id/phase/status`，源文件仅含 `id/size_bytes/sha256`；尚不存在时为 `null`。请求幂等表仅持久化此类白名单投影，不含原文件名、行值、自然键、下载地址或范围展示名。错误文件 POST 返回 `ImportErrorFileAction={batch_id,status,generation,source_preview_version,task}`，也只含最小任务标识。

完整详情通过 GET `ImportBatch` 获取，下列字段均声明存在；未生成的投影显式为 `null`，计数默认为零。精确 Schema 见 [导入数据模型](../../../openapi/components/import-schemas.yaml)。

| 字段                                          | 类型与内容                                                                                  |
| --------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `id`、`parent_batch_id`                       | UUID、可空父批次 UUID。                                                                     |
| `import_type`、`import_type_name`             | 类型标识与安全展示名称。                                                                    |
| `property_company_id`                         | 服务端确定的目标公司 UUID。                                                                 |
| `template`                                    | `{key, version_no, config_hash}`。                                                          |
| `scope`                                       | `{type, id, name}`，服务端确认的范围。                                                      |
| `mode`                                        | `create`。                                                                                  |
| `status`、`phase`                             | 统一批次状态与当前步骤，枚举见下文。                                                        |
| `last_error_code`、`blocked_reason`           | 可空稳定错误码与安全说明，未知结果明确显示待核实。                                          |
| `preview`                                     | 可空 `{version, fingerprint, generated_at, expires_at}`；正版本只在整次预检成功发布后可见。 |
| `apply_policy`                                | 确认前为 `null`，确认后为 `all_rows` 或 `valid_rows_only`。                                 |
| `include_warning_rows`                        | 确认前为 `null`，确认后为布尔值。                                                           |
| `statistics`                                  | `ImportStatistics`，预览统计与执行结果分组。                                                |
| `source_artifact`                             | 可空 `{id, file_name, media_type, size_bytes, sha256, expires_at, available}`。             |
| `active_task`                                 | 可空 `ImportTaskProgress`；不暴露租约、checkpoint、存储键。                                 |
| `created_by`                                  | `{id, name}`，不暴露登录凭据。                                                              |
| `created_at`、`updated_at`、`retention_until` | UTC 时间戳。                                                                                |
| `confirmed_at`、`started_at`、`finished_at`   | 可空 UTC 时间戳。                                                                           |
| `next_actions`                                | 当前身份和状态允许的动作数组。                                                              |

`status` 固定使用 `draft/uploading/prechecking/preview_ready/executing/completed/partial_failed/failed/blocked/cancel_requested/cancelled/expired`。`phase` 使用 `awaiting_source_file/uploading/parse_queued/parse/precheck_queued/precheck/awaiting_confirmation/apply_queued/apply/recovery_queued/recovery/cancelling/finished`，由当前任务和批次状态确定；错误文件任务通过文件资源投影，不改写已结束批次的执行阶段。`uncertain_rows > 0` 时批次必须为 `blocked`、原因 `import.result_uncertain`，不能成为成功、普通失败或取消完成。

`next_actions` 允许值为 `upload_source_file/precheck/confirm/cancel/retry_failed/recover/generate_error_file/download_error_file`。动作失效时从数组移除，但服务端仍独立校验。

`ImportStatistics` 包含 `total_rows`、`preview={create_rows,update_rows,skip_rows,warning_rows,error_rows}`、`execution={created_rows,updated_rows,skipped_rows,failed_rows,uncertain_rows,cancelled_rows,excluded_rows,processed_rows,retryable_failed_rows}`。一期两个 `update` 计数为 0；警告/错误计数可与计划动作重叠。执行统计读取本批次行结果快照；共享操作账本后来重跑成功不能改写旧批次实际执行历史。`retryable_failed_rows` 是当前可用重跑能力计数，可随账本成功、权限变化或保留期到期减少，不属于固定执行事实。

`ImportTaskProgress` 包含 `id/phase/status/progress_done/progress_total/updated_at/last_error_code`，任务阶段为 `parse/precheck/apply/artifact`，状态为 `ready/running/completed/paused/cancelled`；总量尚未确定时 `progress_total=null`，不伪造百分比。`last_error_code` 可空。

### 历史、行、问题与时间线

`GET /v1/import-batches` 使用标准分页；筛选为 `import_type`、`scope_type=company|community`、`scope_id`、`status`、`created_by`、`has_errors`、`created_from`、`created_before`。`scope_id` 要求同时提供 `scope_type`。平台可另传 `property_company_id`，物业传入返回 `422`。排序白名单为 `created_at,id`、`-created_at,-id`、`updated_at,id`、`-updated_at,-id`，默认 `-created_at,-id`。`ImportBatchPage.items` 为 `ImportBatch[]`。

`GET .../rows` 在解析/预检处理中返回 `409 import.batch_state_conflict`，不展示半成品或旧预览；其他阶段使用标准分页，按 `source_row_no,id` 升序；筛选为 `precheck_status=pending|valid|warning|error`、`execution_status=pending|created|skipped|failed|uncertain|cancelled|excluded`、`planned_action=none|create|skip|conflict`、正整数 `row_no`、`field_key`。单行 `ImportRow` 包含 `id/row_no/precheck_status/planned_action/raw_values/normalized_values/issue_count/execution_status/result_code/result_message/result_at`；结果说明与时间可空。原始和规范化对象由服务端按字段权限投影，保留期外不返回敏感快照。`excluded` 区分预检未通过或用户策略排除，`result_code/result_message` 从本批次校验结果、确认策略和本批次问题快照派生安全原因，不能从共享操作最新错误推导旧结果；`cancelled` 仅表示本批次取消未执行。

`GET .../issues` 在解析/预检处理中返回 `409 import.batch_state_conflict`；其他阶段使用标准分页，按原行号空值优先、`id` 升序；筛选为 `severity=warning|error`、`phase=parse|precheck|apply`、正整数 `row_no`、`field_key`、`code`、`retryable`。默认返回已结束解析阶段版本 0 的固定问题、当前已发布预览的预检问题以及本批次执行问题；解析失败未形成预览时也可查询版本 0 的问题。`ImportIssue` 包含 `id/preview_version/phase/row_no/column_index/column_name/field_key/cell_reference/severity/code/message/suggestion/raw_value/normalized_value/retryable`。定位不适用时为 `null`，文件级问题可无行号；字段值使用授权 JSON 标量或 `null`，缺少字段权限不借问题说明泄露原值。`retryable` 必须来自稳定分类与操作当前状态。

`GET .../events` 使用标准分页，`sort` 只允许 `created_at,id` 或 `-created_at,-id`，默认 `created_at,id`。`ImportEvent = {id, event_type, phase, message, created_at}`；`phase` 可空且只包含安全阶段，`event_type/message` 由服务端白名单映射。时间线展示状态、任务阶段和文件生命周期，不暴露原始值、自然键、内部异常或租约，也不替代管理员审计。

## 重预检与确认

`POST .../precheck` 使用 JSON `{preview_version: integer >= 0}` 和幂等键；只允许源快照仍保留、无执行确认、无活动任务且未取消/过期的批次。传入版本必须等于当前发布版本，否则 `409 import.preview_stale`。解析已完成时复用固定源行并安排原预检任务；未完整解析时只允许通过恢复原解析任务继续，不能把半成品作为完整输入。重预检立即撤销旧确认资格，完成后原子发布新版本、摘要、统计和问题集合；旧版本在任务运行时不可确认。

预览生成后有效 24 小时，且不超过批次 `retention_until`。预览过期只禁止确认，可在保留窗口内重预检，不直接销毁批次历史。重预检不能修改模板、范围、文件或延长保留期。

`POST .../confirm` 的 JSON 必须包含 `preview_version`（正整数）、`preview_fingerprint`（64hex）、`apply_policy=all_rows|valid_rows_only`、`include_warning_rows`（布尔值）。不再维护另一份 `execute_policy` 表达。

`all_rows` 要求没有普通错误行；`valid_rows_only` 表示用户显式同意只执行有效行，普通错误行写入本批次 `excluded` 结果。`include_warning_rows=false` 排除警告行，`true` 表示显式确认执行警告行。权限、范围、模板和文件边界问题始终整批阻断，不能用部分执行绕过。过滤后无可执行行返回 `409 import.no_executable_rows`。

服务端检查当前权限与业务能力、固定配置、范围、预览版本/摘要/有效期、批次状态和可执行行；确认策略、确认时间、执行任务、批次更新、审计及请求首次响应同事务提交。Worker 只读取已保存策略。成功返回 `202 ImportBatchAction`，`status=executing`、`phase=apply_queued`，并不表示业务写入已完成。执行分块仍校验业务不变量。

## 取消、重跑与恢复

`POST .../cancel` 无请求体，统一返回 `202 ImportBatchAction`，表示取消请求已持久化；草稿及无活动处理单元也由安全停止流程完成取消，不使用依状态变化的双重成功状态。已结束、过期或未知结果待核实批次返回 `409 import.batch_state_conflict`。在安全边界停止后才能为 `cancelled`；已提交结果保留，仅本批次未执行行标记 `cancelled`，不能把共享操作账本改为取消而影响别的批次。

`POST .../retry-failed` 输入固定 `{selection: retryable_only}`。只选择本批次明确可安全重试的失败行，拒绝未知结果、业务不可重试错误及已清理输入。创建新批次和新行、保留 `parent_batch_id`、原范围与模板身份，并复用原 `operation_key`。返回 `201 ImportRetryResult = {source_batch_id, selected_rows, batch: ImportBatchAction}`，新批次为 `prechecking` 并安排预检；预检后展示新预览，用户必须再次显式确认，不继承原确认策略自动执行。原批次实际执行结果和统计保持稳定；无可重跑行返回 `409 import.no_retryable_rows`。

`POST .../recover` 输入 `{reason: string(1..500)}`，仅用于 `blocked` 或原阶段任务 `paused` 的批次。服务端复核配置、当前权限与范围，以及原任务租约；仍有有效活动租约、阻断原因未解决或结果尚不能安全核实返回 `409 import.recovery_not_allowed`。受理后安排原任务核实/恢复，复用原任务、固定模板及 `operation_key`，不创建替代业务操作或新批次。核实成功提交原批次结果；仍未知则保留 `blocked` 和 `uncertain_rows`。未确认批次恢复只完成解析/预检，不能隐式确认执行；已确认执行恢复使用原已保存策略。输入到期后只允许依据必要内部证据核实原操作并安全结束，不能安排新的业务创建或恢复外部敏感读取。

## 错误文件与保留

`POST .../error-file` 输入 `{format: csv|xlsx, preview_version: positive integer}`，只读取已发布版本和本批次已记录结果。普通错误、执行失败与未知结果均须在文件中清楚标注，未知不伪装为可重试失败。仅允许已发布正整数预览；解析失败、预览版本 0 只提供问题查询，不生成可修复行文件。生成固定版本与代次，独立 `artifact` 任务不改变批次终态；同一批次生成期间不并发安排另一个文件任务，有活动解析、预检或执行任务时不生成，避免半成品结果。无可导出问题返回 `409 import.no_error_rows`。确认、恢复或重预检推进结果后，旧文件投影立即成为 `stale`、`downloadable=false`，必须生成新代次；生成任务的 checkpoint 固定 `source_batch_row_version`；发布和下载同时校验批次版本、预览版本及当前输出代次，artifact 任务进度不改变批次业务版本。不能把执行前的旧文件作为最新执行错误下载。

`ImportErrorFile` 包含 `batch_id/status/generation/source_preview_version/format/task/file_name/media_type/size_bytes/sha256/generated_at/expires_at/last_error_code/downloadable`。`generation` 为正整数或尚未生成时的 `null`，`source_preview_version` 为对应预览版本或 `null`；`status` 为 `not_generated/queued/generating/ready/stale/failed/expired`。未就绪的文件元数据为 `null`，`task` 使用 `ImportTaskProgress` 或 `null`。`GET .../artifacts/error-file` 没有生成记录时返回 `200`、`status=not_generated`，不把批次不存在混为尚未生成。

`GET .../download` 必填查询 `generation`（正整数），避免读取期间代次改变取得另一文件。响应为 `text/csv; charset=utf-8` 或 XLSX 媒体类型的文件流，声明 `Content-Disposition: attachment`、`Content-Length`、`Cache-Control: no-store`、`X-Content-Type-Options: nosniff` 和 `X-Request-ID`。安全文件名由服务端生成，同时提供 ASCII `filename` 和 RFC 5987 `filename*`，不回显路径、控制字符或未经清理的上传名称；不跳转、不返回公开短链。未就绪/代次不匹配返回 `409 import.error_file_not_ready`，过期或已清理返回 `410 import.artifact_expired`。

错误文件包括授权可见的原始错误行、行号、问题字段、错误码、说明和建议，防止 CSV/XLSX 公式注入。生成与下载采用固定的最小安全投影：敏感模板字段始终脱敏，不能按生成者权限增加明文。服务端在生成与下载时都检查当前业务字段权限和范围；未满足最小投影读取要求时拒绝，不能让低权限账号复用高权限文件。私有目录与存储键均不返回前端。

源文件、错误文件及敏感行/问题值保留到 `retention_until`；普通批次为 `created_at + 30d`，重跑批次继承源批次截止时间。到期立即关闭敏感读取、确认、重预检、重跑及错误文件生成/下载；保留最小批次历史、非敏感结果、审计及幂等证据。活动任务或未知结果的必要内部恢复证据延迟物理清理，不能因延期恢复外部读取。重跑、重新生成和原任务恢复不延长源批次窗口；重跑批次的复制输入不得超过源输入有效期。到期不可用操作返回 `410 import.data_expired`，历史/详情/时间线仍按权限读取安全元数据。

## 请求错误与问题码

请求错误遵循 [错误与异常规范](../../api/errors.md)，使用 RFC 9457 `application/problem+json`，公共 `ProblemDetails` 及 `X-Request-ID`。错误 `type=urn:problem:<code>`、`instance=urn:request:<request_id>`；不添加独立 `trace_id` 或请求级 `retryable`。接口启用时将下列 HTTP 领域码登记到现有错误目录并生成目录常量；未实现期间只作为本设计规格。

| HTTP | 领域码                         | 含义                                     |
| ---- | ------------------------------ | ---------------------------------------- |
| 409  | `import.template_unavailable`  | 固定配置或当前类型不可用。               |
| 409  | `import.template_drift`        | 固定配置摘要不一致。                     |
| 409  | `import.preview_stale`         | 预览版本、指纹或有效期失效。             |
| 409  | `import.batch_state_conflict`  | 当前状态或活动任务不允许动作。           |
| 409  | `import.no_executable_rows`    | 策略过滤后没有可执行行。                 |
| 409  | `import.no_retryable_rows`     | 没有明确可安全重试的失败行。             |
| 409  | `import.recovery_not_allowed`  | 尚不满足原任务安全恢复条件。             |
| 409  | `import.idempotency_conflict`  | 同一请求键对应不同输入。                 |
| 409  | `import.no_error_rows`         | 没有可生成错误文件的问题行。             |
| 409  | `import.error_file_not_ready`  | 文件尚未就绪或请求代次不匹配。           |
| 410  | `import.artifact_expired`      | 文件已过期或清理。                       |
| 410  | `import.data_expired`          | 所需输入快照已到保留截止时间。           |
| 413  | `import.file_too_large`        | 源文件超过字节限制。                     |
| 415  | `import.file_type_unsupported` | 实际文件格式不支持。                     |
| 422  | `import.file_invalid`          | 同步可确定的无效文件。                   |
| 429  | `import.rate_limited`          | 明确限流；承诺等待时返回 `Retry-After`。 |

认证、CSRF、权限、不可见资源、参数、基础设施及未知异常复用既有 `401/403/404/422/503/500` 分类。阻断原因 `import.scope_mismatch/import.result_uncertain/import.task_paused` 保存为批次原因或问题码，不能自动当成未登记 HTTP 错误；请求范围不合法按授权与校验规则处理。

行级问题码与 HTTP 目录职责不同，稳定问题包括 `import.required/import.invalid_format/import.invalid_enum/import.duplicate_in_file/import.duplicate_in_system/import.scope_mismatch/import.conflict/import.system_error` 及适配器业务领域码。响应、事件、审计与日志不含 SQL、堆栈、存储地址或未授权值；原始值、规范化值、自然键不进普通日志。

## 验证要求

- 两端契约准确声明输入输出、认证、CSRF、权限、错误、媒体类型与响应头，并通过逐运行端契约检查。
- 无生产适配器时目录为空且不能新建；测试适配器不能进入生产注册表。
- 两端公司、范围、分页总数与文件字段权限隔离，导入权限不能扩张业务权限。
- 所有写动作持久幂等，创建/上传/确认指纹分离，并发确认、取消、重跑和恢复不产生重复业务操作。
- 新预览原子发布，策略显式保存，未知结果先核实，重跑必须再次确认；旧批次快照稳定。
- 取消不修改其他批次共享操作；错误文件固定代次和最小安全投影，流式下载安全且不缓存。
- 24 小时有效期和 30 天窗口一致；清理覆盖敏感自然键，同时保留活动/未知结果的内部恢复证据。
