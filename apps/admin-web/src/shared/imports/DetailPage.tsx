import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from '@umijs/max';
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Form,
  Input,
  Modal,
  Pagination,
  Radio,
  Select,
  Space,
  Timeline,
  Typography,
} from 'antd';
import { useEffect, useState } from 'react';
import { OperationError, ReadError } from '../../components/AdminFeedback';
import { useAdminApp } from '../admin-app-context';
import { useListState } from '../hooks/use-list-state';
import { saveDownload } from './api';
import {
  BatchStatusTag,
  BusinessSummary,
  Statistics,
  TaskProgress,
} from './presentation';
import { fileStatusNames, phaseNames, time } from './values';
import { RowsPanel } from './RowsPanel';
import { SourceUpload } from './UploadPanel';
import { useImports, useImportWrite, isActive } from './runtime';
import type { Batch, ConfirmInput, NextAction } from './types';
const actionPermission: Record<NextAction, string> = {
  upload_source_file: 'upload',
  precheck: 'precheck',
  confirm: 'execute',
  cancel: 'cancel',
  retry_failed: 'retry',
  recover: 'recover',
  generate_error_file: 'generate_error_file',
  download_error_file: 'download',
};
export function ImportsDetailPage() {
  const { batch_id: batchId = '' } = useParams(),
    { api, can, pageRoot, businessDestination } = useImports(),
    nav = useAdminApp(),
    navigate = useNavigate(),
    eventsState = useListState('events_'),
    write = useImportWrite(batchId);
  const [confirmOpen, setConfirmOpen] = useState(false),
    [applyPolicy, setApplyPolicy] =
      useState<ConfirmInput['apply_policy']>('all_rows'),
    [warningChoice, setWarningChoice] = useState<boolean>(),
    [ack, setAck] = useState(false),
    [recoverOpen, setRecoverOpen] = useState(false),
    [reason, setReason] = useState(''),
    [format, setFormat] = useState<'csv' | 'xlsx'>('csv'),
    [fileError, setFileError] = useState<unknown>(null),
    [downloadBusy, setDownloadBusy] = useState(false);
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const query = useQuery({
    queryKey: ['imports', batchId, 'detail'],
    queryFn: ({ signal }) => api.batch(batchId, signal),
    enabled: can('read'),
    refetchInterval: (q) =>
      q.state.data && isActive(q.state.data) ? 3000 : false,
  });
  const batch = query.data;
  const file = useQuery({
    queryKey: ['imports', batchId, 'error-file', batch?.updated_at],
    queryFn: ({ signal }) => api.errorFile(batchId, signal),
    enabled: can('read') && !!batch,
    refetchInterval: (q) =>
      ['queued', 'generating'].includes(q.state.data?.status || '')
        ? 3000
        : false,
  });
  const events = useQuery({
    queryKey: [
      'imports',
      batchId,
      'events',
      batch?.updated_at,
      eventsState.page,
      eventsState.pageSize,
    ],
    queryFn: ({ signal }) =>
      api.events(
        batchId,
        {
          page: eventsState.page,
          page_size: eventsState.pageSize,
          sort: 'created_at,id',
        },
        signal,
      ),
    enabled: can('read') && !!batch,
  });
  function allowed(action: NextAction) {
    return (
      !!batch?.next_actions.includes(action) && can(actionPermission[action])
    );
  }
  async function replay(action: string, body: unknown) {
    return write.run(action, body, async (key, original) => {
      switch (action) {
        case 'confirm':
          return api.confirm(batchId, original as ConfirmInput, key);
        case 'precheck':
          return api.precheck(
            batchId,
            original as { preview_version: number },
            key,
          );
        case 'cancel':
          return api.cancel(batchId, key);
        case 'recover':
          return api.recover(batchId, original as { reason: string }, key);
        case 'generate_error_file':
          return api.generateErrorFile(
            batchId,
            original as { format: 'csv' | 'xlsx'; preview_version: number },
            key,
          );
        case 'retry': {
          const result = await api.retry(batchId, key);
          navigate(nav.path(`${pageRoot}/${result.batch.batch_id}`));
          return result;
        }
        default:
          throw new Error('请使用原文件恢复上传');
      }
    });
  }
  if (query.isError)
    return (
      <PageContainer title="导入批次">
        <ReadError error={query.error} retry={() => void query.refetch()} />
      </PageContainer>
    );
  if (!batch)
    return (
      <PageContainer title="导入批次">
        <Card loading />
      </PageContainer>
    );
  const retained = Date.parse(batch.retention_until) > now,
    previewFresh =
      !!batch.preview && Date.parse(batch.preview.expires_at) > now,
    p = batch.statistics.preview,
    destination = businessDestination?.(batch.import_type, batch.scope);
  return (
    <PageContainer
      title={batch.import_type_name}
      extra={
        <Space>
          <BatchStatusTag status={batch.status} />
          <Button
            onClick={() => {
              void query.refetch();
              void file.refetch();
              void events.refetch();
            }}
          >
            刷新
          </Button>
          <Link to={nav.path(pageRoot)}>返回导入中心</Link>
          {destination?.canNavigate && (
            <Button
              onClick={() => {
                void destination
                  .prepareNavigation()
                  .then(() => navigate(nav.path(destination.path)));
              }}
            >
              返回{destination.label}
            </Button>
          )}
        </Space>
      }
    >
      <Space orientation="vertical" style={{ width: '100%' }}>
        <OperationError error={write.error || fileError} />
        {write.pending.length > 0 && (
          <Alert
            showIcon
            type="warning"
            title="提交结果正在核实，请勿重复点击"
            description={
              <Space orientation="vertical">
                {write.pending.map((item) => (
                  <Space key={item.action}>
                    <Typography.Text>
                      {item.action === 'upload'
                        ? '请先核实批次；仍可上传时重新选择原文件。'
                        : `待核实动作：${item.action}`}
                    </Typography.Text>
                    {item.action !== 'upload' &&
                      can(
                        item.action === 'confirm' ? 'execute' : item.action,
                      ) && (
                        <Button
                          disabled={write.busy}
                          onClick={() => void replay(item.action, item.body)}
                        >
                          使用原请求核实结果
                        </Button>
                      )}
                  </Space>
                ))}
              </Space>
            }
          />
        )}
        {batch.blocked_reason && (
          <Alert
            showIcon
            type="warning"
            title={batch.blocked_reason}
            description={batch.last_error_code}
          />
        )}
        {!retained && (
          <Alert
            type="warning"
            title="输入和敏感快照已到保留截止时间"
            description="仅展示安全历史和已记录结果，不能继续确认、重跑或重建文件。"
          />
        )}
        <Card title="批次信息">
          <Descriptions
            column={2}
            items={[
              {
                key: 'type',
                label: '导入类型',
                children: batch.import_type_name,
              },
              {
                key: 'scope',
                label: '锁定范围',
                children: `${batch.scope.name}（范围已锁定）`,
              },
              {
                key: 'template',
                label: '固定模板',
                children: `${batch.template.key} v${batch.template.version_no}`,
              },
              {
                key: 'mode',
                label: '模式',
                children: '创建模式，不会更新已有数据',
              },
              {
                key: 'phase',
                label: '当前阶段',
                children: phaseNames[batch.phase] || batch.phase,
              },
              {
                key: 'source',
                label: '源文件',
                children: batch.source_artifact?.file_name || '未上传或已清理',
              },
              {
                key: 'creator',
                label: '创建人',
                children: batch.created_by.name,
              },
              {
                key: 'created',
                label: '创建时间',
                children: time(batch.created_at),
              },
              {
                key: 'updated',
                label: '最近更新',
                children: time(batch.updated_at),
              },
              {
                key: 'retention',
                label: '输入保留至',
                children: time(batch.retention_until),
              },
              {
                key: 'preview',
                label: '预览有效期',
                children: time(batch.preview?.expires_at || null),
              },
              {
                key: 'parent',
                label: '来源批次',
                children: batch.parent_batch_id ? (
                  <Link to={nav.path(`${pageRoot}/${batch.parent_batch_id}`)}>
                    查看来源批次
                  </Link>
                ) : (
                  '—'
                ),
              },
              {
                key: 'policy',
                label: '已保存执行策略',
                children: batch.apply_policy
                  ? batch.apply_policy === 'all_rows'
                    ? '全部通过行'
                    : '仅执行通过行'
                  : '尚未确认',
              },
              {
                key: 'warnings',
                label: '执行警告行',
                children:
                  batch.include_warning_rows === null
                    ? '尚未确认'
                    : batch.include_warning_rows
                      ? '是'
                      : '否',
              },
            ]}
          />
          <TaskProgress task={batch.active_task} />
        </Card>
        {allowed('upload_source_file') && retained && (
          <SourceUpload
            batchId={batch.id}
            refresh={() => void query.refetch()}
          />
        )}
        <Statistics batch={batch} />
        <BusinessSummary preview={batch.business_preview} comparison />
        {!batch.confirmed_at && (
          <Alert
            showIcon
            type="info"
            title="当前仍处于预览阶段，尚未写入正式业务数据"
          />
        )}
        {batch.preview && !previewFresh && !batch.confirmed_at && (
          <Alert type="warning" title="预览已过期，请重新预检后再次确认" />
        )}
        <Space wrap>
          {allowed('confirm') && (
            <Button
              type="primary"
              disabled={
                write.busy ||
                write.pending.length > 0 ||
                !previewFresh ||
                !retained
              }
              onClick={() => {
                setApplyPolicy('all_rows');
                setWarningChoice(undefined);
                setAck(false);
                setConfirmOpen(true);
              }}
            >
              确认执行
            </Button>
          )}
          {allowed('precheck') && (
            <Button
              disabled={write.busy || write.pending.length > 0 || !retained}
              onClick={() =>
                void replay('precheck', {
                  preview_version: batch.preview?.version || 0,
                })
              }
            >
              重新预检
            </Button>
          )}
          {allowed('cancel') && (
            <Button
              danger
              disabled={write.busy || write.pending.length > 0}
              onClick={() =>
                Modal.confirm({
                  title: '请求安全停止此批次？',
                  content:
                    '已提交的结果会保留；停止未提交处理单元后才显示已取消。这不会回滚已创建数据。',
                  onOk: () => replay('cancel', undefined),
                })
              }
            >
              取消批次
            </Button>
          )}
          {allowed('retry_failed') && (
            <Button
              disabled={
                write.busy ||
                write.pending.length > 0 ||
                !retained ||
                batch.statistics.execution.uncertain_rows > 0 ||
                batch.statistics.execution.retryable_failed_rows === 0
              }
              onClick={() =>
                Modal.confirm({
                  title: '为明确可安全重试的失败行创建新批次？',
                  content: `当前 ${batch.statistics.execution.retryable_failed_rows} 行可安全重试。新批次需要重新预检和再次确认，原批次结果保持不变。`,
                  onOk: () => replay('retry', { selection: 'retryable_only' }),
                })
              }
            >
              失败行重跑
            </Button>
          )}
          {allowed('recover') && (
            <Button
              disabled={write.busy || write.pending.length > 0}
              onClick={() => {
                setReason('');
                setRecoverOpen(true);
              }}
            >
              核实并恢复原任务
            </Button>
          )}
        </Space>
        {retained &&
          !['draft', 'uploading', 'prechecking', 'cancel_requested'].includes(
            batch.status,
          ) && (
            <Card title="行预览、问题与本批次结果">
              <RowsPanel batch={batch} />
            </Card>
          )}
        <Card title="错误文件">
          <Space orientation="vertical" style={{ width: '100%' }}>
            {file.isError ? (
              <ReadError error={file.error} retry={() => void file.refetch()} />
            ) : (
              <>
                <Typography.Text>
                  {file.data
                    ? fileStatusNames[file.data.status]
                    : '正在读取文件状态'}
                </Typography.Text>
                {file.data?.last_error_code && (
                  <Typography.Text type="danger">
                    {file.data.last_error_code}
                  </Typography.Text>
                )}
                <TaskProgress task={file.data?.task || null} />
                {file.data?.generation && (
                  <Typography.Text>
                    代次 {file.data.generation} · 预览 v
                    {file.data.source_preview_version} ·{' '}
                    {file.data.file_name || '文件尚未就绪'}
                  </Typography.Text>
                )}
              </>
            )}
            <Space>
              <Select
                aria-label="错误文件格式"
                value={format}
                onChange={setFormat}
                options={[
                  { value: 'csv', label: 'CSV' },
                  { value: 'xlsx', label: 'XLSX' },
                ]}
              />
              {allowed('generate_error_file') && (
                <Button
                  disabled={
                    write.busy ||
                    write.pending.length > 0 ||
                    !retained ||
                    !batch.preview ||
                    ['queued', 'generating'].includes(file.data?.status || '')
                  }
                  onClick={() =>
                    void replay('generate_error_file', {
                      format,
                      preview_version: batch.preview?.version,
                    })
                  }
                >
                  生成错误文件
                </Button>
              )}
              {allowed('download_error_file') && (
                <Button
                  disabled={
                    !retained ||
                    !file.data?.downloadable ||
                    !file.data.generation
                  }
                  loading={downloadBusy}
                  onClick={() => {
                    setDownloadBusy(true);
                    setFileError(null);
                    void api
                      .download(batchId, file.data!.generation!)
                      .then(saveDownload)
                      .catch(setFileError)
                      .finally(() => {
                        setDownloadBusy(false);
                        void file.refetch();
                      });
                  }}
                >
                  下载当前代次错误文件
                </Button>
              )}
            </Space>
            <Typography.Text type="secondary">
              错误、失败与待核实结果分别标注。敏感字段始终脱敏；预览或执行结果变化后旧文件立即失效。
            </Typography.Text>
          </Space>
        </Card>
        <Card title="操作时间线">
          {events.isError ? (
            <ReadError
              error={events.error}
              retry={() => void events.refetch()}
            />
          ) : (
            <>
              <Timeline
                items={events.data?.items.map((event) => ({
                  key: event.id,
                  content: (
                    <>
                      <Typography.Text>
                        {time(event.created_at)} · {event.message}
                      </Typography.Text>
                      {event.phase && <div>{phaseNames[event.phase]}</div>}
                    </>
                  ),
                }))}
              />
              <Pagination
                {...eventsState.pagination}
                total={events.data?.total}
              />
            </>
          )}
        </Card>
        <Modal
          title="确认执行导入"
          open={confirmOpen}
          confirmLoading={write.busy}
          onCancel={() => setConfirmOpen(false)}
          okText="确认并安排执行"
          okButtonProps={{
            disabled:
              !ack ||
              warningChoice === undefined ||
              (p.error_rows > 0 && applyPolicy === 'all_rows') ||
              !previewFresh ||
              !allowed('confirm') ||
              write.pending.length > 0,
          }}
          onOk={() => {
            if (!batch.preview || warningChoice === undefined) return;
            void replay('confirm', {
              preview_version: batch.preview.version,
              preview_fingerprint: batch.preview.fingerprint,
              apply_policy: applyPolicy,
              include_warning_rows: warningChoice,
            }).then((result) => {
              if (result) setConfirmOpen(false);
            });
          }}
        >
          <ConfirmSummary batch={batch} />
          <BusinessSummary
            preview={batch.business_preview}
            includeWarningRows={warningChoice}
            blocked={applyPolicy === 'all_rows' && p.error_rows > 0}
          />
          {destination?.confirmationNotice && (
            <Alert type="warning" title={destination.confirmationNotice} />
          )}
          <Form layout="vertical">
            <Form.Item label="执行策略">
              <Radio.Group
                value={applyPolicy}
                onChange={(event) => setApplyPolicy(event.target.value)}
                options={[
                  {
                    value: 'all_rows',
                    label: '全部通过后执行（有错误时禁止）',
                  },
                  {
                    value: 'valid_rows_only',
                    label: '仅执行通过行，排除普通错误行',
                  },
                ]}
              />
            </Form.Item>
            <Form.Item label="是否执行警告行（必须显式选择）">
              <Radio.Group
                value={warningChoice}
                onChange={(event) => setWarningChoice(event.target.value)}
                options={[
                  { value: true, label: '执行警告行' },
                  { value: false, label: '排除警告行' },
                ]}
              />
            </Form.Item>
            <Checkbox
              checked={ack}
              onChange={(event) => setAck(event.target.checked)}
            >
              我已确认锁定范围、模板版本与执行策略
            </Checkbox>
          </Form>
          <Typography.Paragraph type="secondary">
            权限、范围、模板等边界问题仍会整批阻断。受理后展示任务进度，不表示业务数据已写入。
          </Typography.Paragraph>
        </Modal>
        <Modal
          title="核实并恢复原任务"
          open={recoverOpen}
          confirmLoading={write.busy}
          okButtonProps={{
            disabled:
              !reason.trim() || write.pending.length > 0 || !allowed('recover'),
          }}
          onCancel={() => setRecoverOpen(false)}
          onOk={() =>
            void replay('recover', { reason: reason.trim() }).then((result) => {
              if (result) setRecoverOpen(false);
            })
          }
        >
          <Typography.Paragraph>
            仅复用原任务、原操作键及已保存策略。未知结果会继续保持待核实。
          </Typography.Paragraph>
          <Input.TextArea
            aria-label="恢复原因"
            value={reason}
            maxLength={500}
            showCount
            onChange={(event) => setReason(event.target.value)}
          />
        </Modal>
      </Space>
    </PageContainer>
  );
}
function ConfirmSummary({ batch }: { batch: Batch }) {
  const p = batch.statistics.preview;
  return (
    <Descriptions
      column={1}
      size="small"
      items={[
        { key: 'scope', label: '影响范围', children: batch.scope.name },
        {
          key: 'template',
          label: '模板版本',
          children: `v${batch.template.version_no}`,
        },
        { key: 'mode', label: '模式', children: '仅创建，不更新已有数据' },
        {
          key: 'expiry',
          label: '预览有效至',
          children: time(batch.preview?.expires_at || null),
        },
        {
          key: 'total',
          label: '预计处理行数',
          children: batch.statistics.total_rows,
        },
        {
          key: 'count',
          label: '计划与问题',
          children: `新增 ${p.create_rows}，跳过 ${p.skip_rows}，警告 ${p.warning_rows}，错误 ${p.error_rows}`,
        },
      ]}
    />
  );
}
