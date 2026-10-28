import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Checkbox,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Radio,
  Select,
  Space,
  Spin,
  Steps,
  Table,
  Tabs,
  Tag,
  Timeline,
} from 'antd';
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { PageHeader, Panel, DetailGrid } from '../ui';
import { useResource } from '../hooks';
import { ApiError } from '../request';
import { saveFile } from './api';
import {
  BatchTag,
  ErrorNotice,
  Stats,
  TaskProgress,
  batchNames,
  cents,
  notices,
  phaseNames,
  rowNames,
  scalar,
  time,
} from './presentation';
import type { FlowPageProps, ImportsRuntime } from './runtime';
import type { Batch, ConfirmInput, ImportRow, NextAction } from './types';
const permissions: Record<NextAction, string> = {
  upload_source_file: 'upload',
  precheck: 'precheck',
  confirm: 'execute',
  cancel: 'cancel',
  retry_failed: 'retry',
  recover: 'recover',
  generate_error_file: 'generate_error_file',
  download_error_file: 'download',
};
const feeBasisFieldWidths: Record<string, number> = {
  house_label: 220,
  effective_from_month: 120,
  comparison_version: 130,
  old_basis: 280,
  new_basis: 280,
  changes: 240,
  calculated_amount_cents: 140,
  effective_period: 220,
  action_reason: 220,
  change_reason: 200,
  result_version: 320,
  result_source: 140,
};
export function ImportDetail({
  runtime: r,
  params,
  go,
}: FlowPageProps & { runtime: ImportsRuntime }) {
  const id = params.id || params.batch_id || '';
  const setDirty = r.setDirty;
  const client = useQueryClient();
  const { message } = App.useApp();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const keys = useRef(new Map<string, string>());
  const [filter, setFilter] = useState('all');
  const [rowPage, setRowPage] = useState(1);
  const [issuePage, setIssuePage] = useState(1);
  const [eventPage, setEventPage] = useState(1);
  const [row, setRow] = useState<ImportRow>();
  const [action, setAction] = useState<'confirm' | 'cancel' | 'recover' | null>(
    null,
  );
  const [discard, setDiscard] = useState(false);
  const [confirmStep, setConfirmStep] = useState(0);
  const [policy, setPolicy] =
    useState<ConfirmInput['apply_policy']>('all_rows');
  const [warnings, setWarnings] = useState<boolean>();
  const [ack, setAck] = useState(false);
  const [reason, setReason] = useState('');
  const [snapshot, setSnapshot] = useState<Batch>();
  const [format, setFormat] = useState<'csv' | 'xlsx'>('xlsx');
  const resource = useResource(
    ['imports', 'batch', id],
    () => r.api.batch(id),
    !!id,
    2500,
  );
  const b = resource.data;
  const working =
    !!b &&
    ['uploading', 'prechecking', 'executing', 'cancel_requested'].includes(
      b.status,
    );
  const rowsReady = !!b && !['uploading', 'prechecking'].includes(b.status);
  const rows = useResource(
    [
      'imports',
      'rows',
      id,
      filter,
      rowPage,
      b?.preview?.version,
      b?.updated_at,
    ],
    () =>
      r.api.rows(id, {
        page: rowPage,
        page_size: 20,
        ...(filter === 'error' || filter === 'warning'
          ? { precheck_status: filter }
          : {}),
        ...(filter === 'failed' ||
        filter === 'uncertain' ||
        filter === 'excluded'
          ? { execution_status: filter }
          : {}),
      }),
    rowsReady,
  );
  const issues = useResource(
    ['imports', 'issues', id, issuePage, b?.preview?.version, b?.updated_at],
    () => r.api.issues(id, { page: issuePage, page_size: 20 }),
    rowsReady,
  );
  const events = useResource(
    ['imports', 'events', id, eventPage, b?.updated_at],
    () =>
      r.api.events(id, {
        page: eventPage,
        page_size: 20,
        sort: '-created_at,-id',
      }),
    !!b,
  );
  const rowIssues = useResource(
    ['imports', 'row-issues', id, row?.row_no, b?.preview?.version],
    () => r.api.issues(id, { row_no: row!.row_no, page: 1, page_size: 100 }),
    !!row && rowsReady,
  );
  const artifact = useResource(
    ['imports', 'error-file', id, b?.updated_at],
    () => r.api.errorFile(id),
    !!b,
    3000,
  );
  const dirty =
    !!action &&
    (policy !== 'all_rows' || warnings !== undefined || ack || !!reason.trim());
  useEffect(() => {
    setDirty(dirty);
    if (!dirty) setDiscard(false);
    return () => setDirty(false);
  }, [dirty, setDirty]);
  useEffect(() => {
    setFilter('all');
    setRowPage(1);
    setIssuePage(1);
    setEventPage(1);
    setRow(undefined);
    setAction(null);
    setError(undefined);
  }, [id]);
  const allowed = (name: NextAction) =>
    !!b?.next_actions.includes(name) && r.can(permissions[name], b.import_type);
  const refresh = async () => {
    await client.invalidateQueries({
      predicate: (query) => query.queryKey.includes('imports'),
    });
  };
  const key = (signature: string) => {
    if (!keys.current.has(signature))
      keys.current.set(signature, crypto.randomUUID());
    return keys.current.get(signature)!;
  };
  async function run(
    work: () => Promise<unknown>,
    success: string,
    done?: () => void,
  ) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(undefined);
    try {
      await work();
      message.info(success);
      done?.();
      await refresh();
    } catch (e) {
      setError(e);
      await refresh();
      if (!(e instanceof ApiError) || e.status === 0 || e.status >= 500)
        message.warning('请求结果待核实，已重新读取原批次；请勿新建替代操作。');
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  const close = () => {
    setAction(null);
    setDiscard(false);
    r.setDirty(false);
  };
  const requestClose = () => {
    if (busy) return;
    if (dirty) setDiscard(true);
    else close();
  };
  const open = (next: 'confirm' | 'cancel' | 'recover') => {
    setPolicy('all_rows');
    setWarnings(undefined);
    setAck(false);
    setReason('');
    setConfirmStep(0);
    setDiscard(false);
    setSnapshot(b);
    setAction(next);
  };
  function confirm() {
    if (!b || !snapshot?.preview || warnings === undefined) return;
    const body: ConfirmInput = {
      preview_version: snapshot.preview.version,
      preview_fingerprint: snapshot.preview.fingerprint,
      apply_policy: policy,
      include_warning_rows: warnings,
    };
    void run(
      () =>
        r.api.confirm(id, body, key(`confirm:${id}:${JSON.stringify(body)}`)),
      '执行任务已安排，请查看实际进度',
      close,
    );
  }
  if (resource.isLoading)
    return (
      <Panel>
        <Spin />
      </Panel>
    );
  if (!b)
    return (
      <>
        <PageHeader title="导入批次" back={() => go('imports')} />
        <ErrorNotice
          error={resource.error}
          retry={() => void resource.refetch()}
        />
        {!id && <Empty description="未指定批次" />}
      </>
    );
  const e = b.statistics.execution,
    p = b.statistics.preview;
  const feeBasisImport = b.import_type === 'property_fee_basis_versions';
  const previewFields = b.business_preview?.fields || [];
  const previewWidth = feeBasisImport
    ? previewFields.reduce(
        (width, field) => width + (feeBasisFieldWidths[field.key] ?? 180),
        85 + 100 + 120 + 200 + 100,
      )
    : 850;
  const ended = [
    'completed',
    'partial_failed',
    'cancelled',
    'expired',
    'failed',
  ].includes(b.status);
  const stage = ended
    ? 4
    : b.status === 'preview_ready'
      ? 2
      : b.confirmed_at
        ? 3
        : b.status === 'draft'
          ? 0
          : 1;
  const stale =
    !!snapshot?.preview &&
    (b.preview?.fingerprint !== snapshot.preview.fingerprint ||
      b.preview?.version !== snapshot.preview.version ||
      Date.parse(snapshot.preview.expires_at) <= Date.now());
  const back = () => {
    let prior: Record<string, string> = {};
    try {
      prior = JSON.parse(params.return || '{}') as Record<string, string>;
    } catch {
      /* Use list defaults. */
    }
    go('imports', prior);
  };
  return (
    <>
      <PageHeader
        title={`${b.import_type_name}导入`}
        description={`${b.id} · ${b.source_artifact?.file_name || '尚未上传文件'}`}
        back={back}
        extra={
          <>
            <BatchTag value={b.status} />
            {allowed('retry_failed') && (
              <Button
                loading={busy}
                icon={<ReloadOutlined />}
                onClick={() =>
                  void run(async () => {
                    const result = await r.api.retry(
                      id,
                      key(`retry:${id}:${b.updated_at}`),
                    );
                    go('import-detail', { id: result.batch.batch_id });
                  }, '已创建失败行新批次，请重新核对预检并确认')
                }
              >
                失败行重跑
              </Button>
            )}
          </>
        }
      />
      <ErrorNotice
        error={resource.error}
        retry={() => void resource.refetch()}
      />
      <ErrorNotice error={error} />
      <Panel>
        <Steps
          current={stage}
          items={[
            {
              title: '文件与范围',
              content: b.source_artifact ? '已锁定' : '等待上传',
            },
            { title: '解析预检', content: phaseNames[b.phase] || b.phase },
            {
              title: '核对并确认',
              content: b.preview ? `预览 v${b.preview.version}` : '尚未发布',
            },
            {
              title: '异步执行',
              content: b.confirmed_at ? '策略已保存' : undefined,
            },
            { title: '查看结果' },
          ]}
        />
      </Panel>
      <Panel title="批次摘要">
        <DetailGrid
          items={[
            [
              b.scope.type === 'community' ? '目标小区' : '目标公司',
              b.scope.name,
            ],
            ['业务类型', b.import_type_name],
            ['模式 / 模板', `仅创建 · v${b.template.version_no}`],
            ['预览有效至', time(b.preview?.expires_at)],
            [
              '来源批次',
              b.parent_batch_id ? (
                <Button
                  type="link"
                  onClick={() =>
                    go('import-detail', { id: b.parent_batch_id! })
                  }
                >
                  {b.parent_batch_id}
                </Button>
              ) : (
                '独立批次'
              ),
            ],
            ['操作者', b.created_by.name],
            ['数据保留至', time(b.retention_until)],
            ['当前阶段', phaseNames[b.phase] || b.phase],
          ]}
        />
        {!b.confirmed_at && (
          <Alert
            style={{ marginTop: 20 }}
            type="info"
            showIcon
            title="当前仍处于预览阶段，尚未写入正式业务数据"
          />
        )}
        {b.scope.type === 'community' &&
          r.scope === 'property' &&
          b.scope.id !== r.communityId && (
            <Alert
              style={{ marginTop: 20 }}
              type="info"
              showIcon
              title={`当前批次属于${b.scope.name}，按批次锁定范围展示；顶部小区选择不会改写批次范围。`}
            />
          )}
      </Panel>
      <Stats
        items={
          b.confirmed_at
            ? [
                ['实际成功', e.created_rows + e.updated_rows],
                ['执行失败', e.failed_rows],
                ['业务跳过', e.skipped_rows],
                ['策略排除', e.excluded_rows],
              ]
            : [
                ['总行数', b.preview ? b.statistics.total_rows : '待确定'],
                ['计划新增', p.create_rows],
                ['业务跳过', p.skip_rows],
                ['问题行', `${p.warning_rows} 警告 / ${p.error_rows} 错误`],
              ]
        }
      />
      {b.active_task && (
        <Panel title={phaseNames[b.phase] || '处理进度'}>
          <TaskProgress task={b.active_task} />
          <p style={{ color: '#64748b' }}>
            异步受理不代表业务执行成功，请勿重复提交。
          </p>
        </Panel>
      )}
      {(b.status === 'blocked' || e.uncertain_rows > 0) && (
        <Alert
          showIcon
          type="warning"
          style={{ marginBottom: 20 }}
          title={`存在待核实结果 ${e.uncertain_rows} 行`}
          description={`${b.blocked_reason || '请先核实并恢复原任务。'} 未知结果不计为失败，不能通过失败行重跑创建新操作。`}
        />
      )}
      {ended && (
        <Alert
          showIcon
          style={{ marginBottom: 20 }}
          type={
            b.status === 'completed'
              ? 'success'
              : b.status === 'failed'
                ? 'error'
                : 'warning'
          }
          title={`${batchNames[b.status]}：成功 ${e.created_rows + e.updated_rows} 行、失败 ${e.failed_rows} 行、业务跳过 ${e.skipped_rows} 行、排除 ${e.excluded_rows} 行、取消未执行 ${e.cancelled_rows} 行`}
          description="已提交结果保留。失败重跑只选择可安全重试的行，并需要再次确认。"
        />
      )}
      {b.status === 'draft' && allowed('upload_source_file') && (
        <DraftUpload id={id} runtime={r} busy={busy} run={run} keyFor={key} />
      )}
      <Panel
        title={b.confirmed_at ? '行结果与问题' : '逐行预览'}
        extra={
          <Space>
            <Select
              aria-label="问题文件格式"
              value={format}
              onChange={setFormat}
              options={[
                { value: 'xlsx', label: 'XLSX' },
                { value: 'csv', label: 'CSV' },
              ]}
              style={{ width: 100 }}
            />
            {allowed('generate_error_file') && (
              <Button
                icon={<DownloadOutlined />}
                loading={busy}
                onClick={() =>
                  void run(
                    () =>
                      r.api.generateErrorFile(
                        id,
                        b.preview!.version,
                        format,
                        key(`file:${id}:${b.updated_at}:${format}`),
                      ),
                    '问题文件生成任务已安排',
                  )
                }
              >
                生成问题清单
              </Button>
            )}
            {allowed('download_error_file') &&
              artifact.data?.downloadable &&
              artifact.data.generation !== null && (
                <Button
                  icon={<DownloadOutlined />}
                  onClick={() =>
                    void r.api
                      .download(id, artifact.data!.generation!)
                      .then(saveFile)
                      .catch(setError)
                  }
                >
                  下载问题清单
                </Button>
              )}
          </Space>
        }
      >
        {artifact.data &&
          ['queued', 'generating'].includes(artifact.data.status) && (
            <Alert
              style={{ marginBottom: 16 }}
              type="info"
              showIcon
              title="问题文件正在生成"
              description={
                artifact.data.task ? (
                  <TaskProgress task={artifact.data.task} />
                ) : undefined
              }
            />
          )}
        {artifact.data?.status === 'stale' && (
          <Alert
            style={{ marginBottom: 16 }}
            type="warning"
            title="旧问题文件已失效，请生成当前结果的问题清单"
          />
        )}
        <ErrorNotice error={artifact.error} />
        <Tabs
          activeKey={filter}
          onChange={(value) => {
            setFilter(value);
            setRowPage(1);
          }}
          items={[
            ['all', '全部'],
            ['error', '错误'],
            ['warning', '警告'],
            ['failed', '失败'],
            ['uncertain', '待核实'],
            ['excluded', '排除'],
          ].map(([key, label]) => ({ key, label }))}
        />
        {!rowsReady ? (
          <Alert
            type="info"
            showIcon
            title="正在解析或预检，完整预览发布后可查看行结果"
          />
        ) : (
          <>
            <ErrorNotice error={rows.error} retry={() => void rows.refetch()} />
            <Table<ImportRow>
              rowKey="id"
              loading={rows.isLoading}
              dataSource={rows.data?.items}
              scroll={{ x: previewWidth }}
              tableLayout={feeBasisImport ? 'fixed' : undefined}
              pagination={{
                current: rowPage,
                pageSize: 20,
                total: rows.data?.total,
                showSizeChanger: false,
                showTotal: (total) => `共 ${total} 行`,
                onChange: setRowPage,
              }}
              columns={[
                { title: '原始行', dataIndex: 'row_no', width: 85 },
                ...previewFields.map((field) => ({
                  title: field.label,
                  key: field.key,
                  width: feeBasisImport
                    ? (feeBasisFieldWidths[field.key] ?? 180)
                    : undefined,
                  render: (_: unknown, item: ImportRow) =>
                    field.format === 'money_cents'
                      ? cents(
                          item.business_values?.[field.key] as
                            string | number | null,
                        )
                      : scalar(item.business_values?.[field.key]),
                })),
                {
                  title: '计划动作',
                  dataIndex: 'planned_action',
                  width: feeBasisImport ? 100 : undefined,
                  render: (value) => rowNames[value] || value,
                },
                {
                  title: b.confirmed_at ? '执行结果' : '校验结果',
                  width: feeBasisImport ? 120 : undefined,
                  render: (_, item) => (
                    <Tag
                      color={
                        ['failed', 'uncertain', 'error'].includes(
                          b.confirmed_at
                            ? item.execution_status
                            : item.precheck_status,
                        )
                          ? 'warning'
                          : undefined
                      }
                    >
                      {
                        rowNames[
                          b.confirmed_at
                            ? item.execution_status
                            : item.precheck_status
                        ]
                      }
                    </Tag>
                  ),
                },
                {
                  title: '说明',
                  dataIndex: 'result_message',
                  width: feeBasisImport ? 200 : undefined,
                  render: (value) => value || '—',
                },
                {
                  title: '操作',
                  width: feeBasisImport ? 100 : undefined,
                  fixed: feeBasisImport ? 'right' : undefined,
                  render: (_, item) => (
                    <Button type="link" onClick={() => setRow(item)}>
                      查看明细
                    </Button>
                  ),
                },
              ]}
            />
          </>
        )}
      </Panel>
      <Panel title="问题定位">
        <ErrorNotice error={issues.error} retry={() => void issues.refetch()} />
        {rowsReady ? (
          <Table
            rowKey="id"
            loading={issues.isLoading}
            dataSource={issues.data?.items}
            pagination={{
              current: issuePage,
              pageSize: 20,
              total: issues.data?.total,
              showSizeChanger: false,
              onChange: setIssuePage,
            }}
            columns={[
              {
                title: '原始行 / 单元格',
                render: (_, i) =>
                  `${i.row_no ?? '文件级'} / ${i.cell_reference || '—'}`,
              },
              {
                title: '字段',
                render: (_, i) => i.column_name || i.field_key || '—',
              },
              {
                title: '级别',
                dataIndex: 'severity',
                render: (value) => (
                  <Tag color={value === 'error' ? 'error' : 'warning'}>
                    {value === 'error' ? '错误' : '警告'}
                  </Tag>
                ),
              },
              {
                title: '问题与建议',
                render: (_, i) => (
                  <>
                    {i.message}
                    <div style={{ color: '#64748b', fontSize: 12 }}>
                      {i.suggestion}
                    </div>
                  </>
                ),
              },
              {
                title: '安全重试',
                dataIndex: 'retryable',
                render: (value) => (value ? '可安全重试' : '不可重试'),
              },
            ]}
          />
        ) : (
          <Empty description="预检完成后显示完整问题" />
        )}
      </Panel>
      <Panel title="处理时间线">
        <ErrorNotice error={events.error} />
        <Timeline
          items={events.data?.items.map((event) => ({
            content: (
              <>
                <strong>{event.message}</strong>
                <div style={{ color: '#64748b' }}>{time(event.created_at)}</div>
              </>
            ),
          }))}
        />
        {events.data && events.data.total > 20 && (
          <Space>
            <Button
              disabled={eventPage <= 1}
              onClick={() => setEventPage(eventPage - 1)}
            >
              上一页
            </Button>
            <span>
              第 {eventPage} 页 · 共 {events.data.total} 条
            </span>
            <Button
              disabled={eventPage * 20 >= events.data.total}
              onClick={() => setEventPage(eventPage + 1)}
            >
              下一页
            </Button>
          </Space>
        )}
      </Panel>
      {(allowed('confirm') ||
        allowed('cancel') ||
        allowed('recover') ||
        allowed('precheck')) && (
        <Panel
          title="核对后继续"
          extra={
            <Space>
              {allowed('cancel') && (
                <Button danger disabled={busy} onClick={() => open('cancel')}>
                  取消批次
                </Button>
              )}
              {allowed('recover') && (
                <Button disabled={busy} onClick={() => open('recover')}>
                  核实并恢复原任务
                </Button>
              )}
              {allowed('precheck') && (
                <Button
                  loading={busy}
                  onClick={() =>
                    void run(
                      () =>
                        r.api.precheck(
                          id,
                          b.preview?.version || 0,
                          key(`precheck:${id}:${b.preview?.version || 0}`),
                        ),
                      '已安排重新预检，旧预览暂不可确认',
                    )
                  }
                >
                  重新预检
                </Button>
              )}
              {allowed('confirm') && (
                <Button
                  type="primary"
                  disabled={busy || working}
                  onClick={() => open('confirm')}
                >
                  确认执行
                </Button>
              )}
            </Space>
          }
        >
          <p style={{ margin: 0, color: '#64748b' }}>
            {p.error_rows
              ? `有 ${p.error_rows} 行普通数据错误。可修复后新建批次，或显式选择仅执行通过行。`
              : '请核对范围、模板与执行策略。'}{' '}
            范围、权限或模板边界问题始终阻断整批。
          </p>
        </Panel>
      )}
      <Drawer
        title={`原始第 ${row?.row_no || ''} 行`}
        open={!!row}
        size={600}
        onClose={() => setRow(undefined)}
      >
        {row && (
          <>
            <DetailGrid
              items={[
                ['计划动作', rowNames[row.planned_action]],
                ['校验结果', rowNames[row.precheck_status]],
                ['执行结果', rowNames[row.execution_status]],
                ['结果说明', row.result_message || '—'],
                ['结果时间', time(row.result_at)],
              ]}
            />
            <h4 style={{ marginTop: 28 }}>原始值与规范化值</h4>
            <Table
              pagination={false}
              rowKey="key"
              dataSource={Object.keys({
                ...row.raw_values,
                ...row.normalized_values,
              }).map((key) => ({
                key,
                raw: row.raw_values[key],
                normalized: row.normalized_values?.[key],
              }))}
              columns={[
                {
                  title: '字段',
                  render: (_, item) =>
                    b.template_fields?.find((field) => field.key === item.key)
                      ?.label || item.key,
                },
                { title: '原始值', dataIndex: 'raw', render: scalar },
                { title: '规范化值', dataIndex: 'normalized', render: scalar },
              ]}
            />
            <ErrorNotice error={rowIssues.error} />
            {rowIssues.data?.items.map((i) => (
              <Alert
                key={i.id}
                style={{ marginTop: 16 }}
                showIcon
                type={i.severity === 'error' ? 'error' : 'warning'}
                title={`${i.cell_reference || i.column_name || '文件级'} · ${i.message}`}
                description={
                  <>
                    {i.suggestion}
                    <div>错误码：{i.code}</div>
                  </>
                }
              />
            ))}
          </>
        )}
      </Drawer>
      <Modal
        title={
          action === 'confirm'
            ? '确认执行导入'
            : action === 'recover'
              ? '核实并恢复原任务'
              : '取消此批次？'
        }
        open={!!action}
        width={660}
        onCancel={requestClose}
        closable={!busy}
        mask={{ closable: !busy }}
        keyboard={!busy}
        footer={
          <Space>
            {action === 'confirm' && confirmStep === 1 && (
              <Button disabled={busy} onClick={() => setConfirmStep(0)}>
                返回修改策略
              </Button>
            )}
            <Button disabled={busy} onClick={requestClose}>
              取消
            </Button>
            <Button
              type="primary"
              danger={action === 'cancel'}
              loading={busy}
              disabled={
                busy ||
                (action === 'confirm' &&
                  (stale ||
                    !allowed('confirm') ||
                    (confirmStep === 0
                      ? (p.error_rows > 0 && policy === 'all_rows') ||
                        warnings === undefined
                      : !ack))) ||
                (action === 'recover' && !reason.trim())
              }
              onClick={() => {
                if (action === 'confirm') {
                  if (confirmStep === 0) setConfirmStep(1);
                  else confirm();
                } else if (action === 'recover')
                  void run(
                    () =>
                      r.api.recover(
                        id,
                        reason.trim(),
                        key(
                          `recover:${id}:${snapshot?.updated_at}:${reason.trim()}`,
                        ),
                      ),
                    '已安排原任务核实与恢复',
                    close,
                  );
                else
                  void run(
                    () => r.api.cancel(id, key(`cancel:${id}`)),
                    '取消请求已保存，等待任务安全停止',
                    close,
                  );
              }}
            >
              {action === 'confirm'
                ? confirmStep
                  ? '确认并安排执行'
                  : '下一步：核对影响范围'
                : action === 'recover'
                  ? '安排原任务恢复'
                  : '确认取消批次'}
            </Button>
          </Space>
        }
      >
        {discard && (
          <Alert
            style={{ marginBottom: 20 }}
            type="warning"
            showIcon
            title="有未保存的修改"
            description="继续核对，或放弃本次选择后关闭。"
            action={
              <Space>
                <Button size="small" onClick={() => setDiscard(false)}>
                  继续编辑
                </Button>
                <Button danger size="small" onClick={close}>
                  放弃修改
                </Button>
              </Space>
            }
          />
        )}
        {action === 'confirm' && (
          <>
            <Steps
              size="small"
              current={confirmStep}
              items={[{ title: '选择执行策略' }, { title: '确认影响范围' }]}
              style={{ margin: '12px 0 24px' }}
            />
            {stale && (
              <Alert
                type="error"
                showIcon
                title="预览已变化或过期，请关闭并重新核对最新预览"
              />
            )}
            {confirmStep === 0 ? (
              <Form layout="vertical" disabled={busy}>
                <Alert
                  style={{ marginBottom: 18 }}
                  type={p.error_rows ? 'warning' : 'success'}
                  showIcon
                  title={
                    p.error_rows
                      ? `发现 ${p.error_rows} 行普通错误，默认禁止整批执行`
                      : '预检通过，请显式选择警告行策略'
                  }
                />
                <Form.Item label="执行策略">
                  <Radio.Group
                    value={policy}
                    onChange={(event) => setPolicy(event.target.value)}
                  >
                    <Space orientation="vertical">
                      <Radio value="all_rows">
                        全部通过后执行
                        {p.error_rows > 0 && '（当前有错误，无法继续）'}
                      </Radio>
                      <Radio value="valid_rows_only">
                        仅执行通过行，排除普通错误行
                      </Radio>
                    </Space>
                  </Radio.Group>
                </Form.Item>
                <Form.Item label="是否执行警告行 · 必须显式选择">
                  <Radio.Group
                    value={warnings}
                    onChange={(event) => setWarnings(event.target.value)}
                  >
                    <Radio value={true}>执行警告行</Radio>
                    <Radio value={false}>排除警告行</Radio>
                  </Radio.Group>
                </Form.Item>
              </Form>
            ) : (
              <>
                <DetailGrid
                  items={[
                    ['锁定范围', b.scope.name],
                    ['模板 / 模式', `v${b.template.version_no} / 仅创建`],
                    [
                      '普通错误处理',
                      policy === 'valid_rows_only'
                        ? '排除错误行'
                        : '无错误时全批执行',
                    ],
                    ['警告行处理', warnings ? '包含警告行' : '排除警告行'],
                    ...(b.business_preview?.summary || []).map(
                      (s) =>
                        [
                          s.label,
                          s.format === 'money_cents'
                            ? cents(
                                warnings
                                  ? s.with_warning_rows
                                  : s.without_warning_rows,
                              )
                            : warnings
                              ? s.with_warning_rows
                              : s.without_warning_rows,
                        ] as [string, string],
                    ),
                  ]}
                />
                <Alert
                  style={{ margin: '20px 0' }}
                  type="warning"
                  showIcon
                  title={
                    notices[b.import_type] ||
                    '请核对本次导入范围与模板；已成功数据不会回滚。'
                  }
                />
                <Checkbox
                  checked={ack}
                  disabled={busy}
                  onChange={(event) => setAck(event.target.checked)}
                >
                  我已核对范围、模板与执行策略，知晓已成功结果不会回滚。
                </Checkbox>
              </>
            )}
          </>
        )}
        {action === 'recover' && (
          <>
            <Alert
              type="warning"
              showIcon
              title="未知结果先核实原操作，不创建替代批次"
              description="恢复沿用原任务、固定输入和原确认策略。未确认批次恢复后仍需要显式确认。"
              style={{ marginBottom: 20 }}
            />
            <Form layout="vertical">
              <Form.Item label="核实结论与恢复原因" required>
                <Input.TextArea
                  aria-label="核实结论与恢复原因"
                  rows={4}
                  maxLength={500}
                  showCount
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                />
              </Form.Item>
            </Form>
          </>
        )}
        {action === 'cancel' && (
          <p>
            取消只停止尚未提交的处理单元，不回滚已创建的业务数据。提交请求后，等待批次状态确认为“已取消”。
          </p>
        )}
      </Modal>
    </>
  );
}
function DraftUpload({
  id,
  runtime: r,
  busy,
  run,
  keyFor,
}: {
  id: string;
  runtime: ImportsRuntime;
  busy: boolean;
  run: (
    work: () => Promise<unknown>,
    success: string,
    done?: () => void,
  ) => Promise<void>;
  keyFor: (signature: string) => string;
}) {
  const [file, setFile] = useState<File>();
  const [progress, setProgress] = useState<string>('');
  const { message } = App.useApp();
  return (
    <Panel title="继续上传源文件">
      <Alert
        type="info"
        showIcon
        title="批次范围和模板已锁定；上传后会安排解析与预检"
      />
      <Space style={{ marginTop: 20 }}>
        <Input
          type="file"
          accept=".csv,.xlsx"
          disabled={busy}
          onChange={(event) => {
            const next = event.target.files?.[0];
            if (
              next &&
              (!/\.(csv|xlsx)$/i.test(next.name) ||
                !next.size ||
                next.size > 10485760)
            ) {
              message.error('请选择不超过 10 MiB 的非空 CSV 或 XLSX');
              return;
            }
            setFile(next);
          }}
        />
        <Button
          type="primary"
          disabled={!file || busy}
          loading={busy}
          onClick={() =>
            void run(
              () =>
                r.api.upload(
                  id,
                  file!,
                  keyFor(
                    `upload:${id}:${file!.name}:${file!.size}:${file!.lastModified}`,
                  ),
                  (done, total) =>
                    setProgress(
                      total
                        ? `${Math.floor((done / total) * 100)}%`
                        : `已发送 ${done} 字节`,
                    ),
                ),
              '文件已接收，正在异步解析与预检',
            )
          }
        >
          上传并预检
        </Button>
        {progress}
      </Space>
    </Panel>
  );
}
