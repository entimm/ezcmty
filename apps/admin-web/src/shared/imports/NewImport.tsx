import { useEffect, useMemo, useRef, useState } from 'react';
import {
  App,
  Alert,
  Button,
  Empty,
  Form,
  Progress,
  Select,
  Space,
  Spin,
  Steps,
  Table,
  Upload,
} from 'antd';
import {
  ArrowRightOutlined,
  CloudUploadOutlined,
  DownloadOutlined,
  FileExcelOutlined,
} from '@ant-design/icons';
import { PageHeader, Panel, DetailGrid } from '../ui';
import { useResource } from '../hooks';
import { ApiError } from '../request';
import { saveFile } from './api';
import { ErrorNotice, notices } from './presentation';
import type { FlowPageProps, ImportsRuntime } from './runtime';
import type { BatchAction, ImportType } from './types';
export function NewImport({
  runtime: r,
  go,
  params,
}: FlowPageProps & { runtime: ImportsRuntime }) {
  const { message } = App.useApp();
  const setDirty = r.setDirty;
  const submitLock = useRef(false);
  const [type, setType] = useState(
    params.import_type === 'bills'
      ? 'property_fee_bills'
      : params.import_type || '',
  );
  const [version, setVersion] = useState<number>();
  const [companyId, setCompanyId] = useState('');
  const [target, setTarget] = useState('');
  const [scopeType, setScopeType] = useState<'company' | 'community'>(
    'community',
  );
  const [step, setStep] = useState(0);
  const [file, setFile] = useState<File>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [uploaded, setUploaded] = useState<number | null>(null);
  const [uploadTotal, setUploadTotal] = useState<number | null>(null);
  const [draft, setDraft] = useState<string>();
  const [unknownResult, setUnknownResult] = useState(false);
  const operation = useRef<{
    create?: { key: string; body: string };
    upload?: { key: string; file: File };
  }>({});
  const types = useResource(
    ['imports', 'types'],
    () => r.api.types(),
    r.can('create'),
  );
  const available = useMemo(
    () =>
      types.data?.items.filter((x) =>
        x.versions.some((v) => v.available_for_new_batches),
      ) || [],
    [types.data],
  );
  const selected = available.find((x) => x.key === type);
  useEffect(() => {
    if (available.length && !available.some((item) => item.key === type)) {
      setType(available[0].key);
    }
  }, [available, type]);
  useEffect(() => {
    const current = available.find((x) => x.key === type);
    if (current) {
      setVersion(
        current.versions
          .filter((v) => v.available_for_new_batches)
          .sort((a, b) => b.version_no - a.version_no)[0]?.version_no,
      );
      setScopeType(
        current.allowed_scope_types.includes('community')
          ? 'community'
          : 'company',
      );
    }
  }, [type, available]);
  const company = useResource(
    ['imports', 'current-company'],
    () => r.company!(),
    r.scope === 'property' && !!r.company,
  );
  const companies = useResource(
    ['imports', 'companies'],
    () => r.companies!(),
    r.scope === 'platform' && !!r.companies && available.length > 0,
  );
  const communities = useResource(
    ['imports', 'communities', companyId],
    () => r.communities!(companyId),
    r.scope === 'platform' &&
      !!r.communities &&
      !!companyId &&
      scopeType === 'community',
  );
  const template = useResource(
    ['imports', 'template', type, version],
    () => r.api.template(type, version!),
    !!type && !!version && r.can('create'),
  );
  useEffect(() => {
    setDirty(!!file || step > 0 || !!draft);
    return () => setDirty(false);
  }, [file, step, draft, setDirty]);
  const targetId =
    r.scope === 'property'
      ? scopeType === 'community'
        ? r.communityId
        : company.data?.id || ''
      : scopeType === 'community'
        ? target
        : companyId;
  const targetName =
    r.scope === 'property'
      ? scopeType === 'community'
        ? r.community?.name
        : company.data?.name
      : scopeType === 'community'
        ? communities.data?.find((x) => x.id === target)?.name
        : companies.data?.find((x) => x.id === companyId)?.name;
  async function submit() {
    if (!file || !selected || !version || !targetId || submitLock.current)
      return;
    submitLock.current = true;
    setBusy(true);
    setError(undefined);
    setStep(2);
    setUploaded(null);
    setUnknownResult(false);
    let batchId = draft;
    try {
      if (!batchId) {
        const body = {
          import_type: type,
          template_version_no: version,
          scope: { type: scopeType, id: targetId },
          mode: 'create' as const,
          ...(r.scope === 'platform' ? { property_company_id: companyId } : {}),
        };
        const signature = JSON.stringify(body);
        if (
          operation.current.create &&
          operation.current.create.body !== signature
        )
          throw new Error('上次创建结果尚未核实，请先返回导入历史核对。');
        operation.current.create ??= {
          key: crypto.randomUUID(),
          body: signature,
        };
        const result = await r.api.create(body, operation.current.create.key);
        batchId = result.batch_id;
        setDraft(batchId);
      }
      if (!operation.current.upload || operation.current.upload.file !== file)
        operation.current.upload = { key: crypto.randomUUID(), file };
      const result: BatchAction = await r.api.upload(
        batchId,
        file,
        operation.current.upload.key,
        (done, total) => {
          setUploaded(done);
          setUploadTotal(total);
        },
      );
      r.setDirty(false);
      message.info('文件已接收，正在异步解析与预检');
      go('import-detail', { id: result.batch_id, return: params.return });
    } catch (e) {
      setError(e);
      if (!(e instanceof ApiError) || e.status >= 500 || e.status === 0) {
        setUnknownResult(true);
        if (batchId) {
          try {
            const current = await r.api.batch(batchId);
            if (current.status !== 'draft') {
              r.setDirty(false);
              go('import-detail', { id: batchId });
            }
          } catch {
            /* Original error remains visible. */
          }
        }
      }
    } finally {
      submitLock.current = false;
      setBusy(false);
    }
  }
  const back = () => go('imports');
  return (
    <>
      <PageHeader
        title="新建导入"
        description="先确定范围和模板，再上传文件；确认前不会创建业务数据。"
        back={back}
      />
      <Panel>
        <Steps
          current={step}
          items={[
            { title: '类型与范围' },
            { title: '模板与文件' },
            { title: '解析与预检' },
          ]}
        />
      </Panel>
      <ErrorNotice error={types.error} retry={() => void types.refetch()} />
      {types.isLoading ? (
        <Spin />
      ) : !r.can('create') ? (
        <Panel>
          <Empty description="当前没有新建导入权限" />
        </Panel>
      ) : available.length === 0 ? (
        <Panel>
          <Empty
            description={
              r.scope === 'platform'
                ? '平台尚无可用导入类型，无法新建批次'
                : '当前没有可用导入类型'
            }
          />
        </Panel>
      ) : (
        <Panel
          title={
            [
              '确定本次导入范围',
              '按标准模板准备文件',
              '正在接收文件与生成完整预览',
            ][step]
          }
        >
          <ErrorNotice error={error} />
          <ErrorNotice
            error={company.error || companies.error || communities.error}
          />
          {step === 0 && (
            <Form layout="vertical" style={{ maxWidth: 680 }}>
              <Form.Item label="导入类型">
                <Select
                  value={type}
                  options={available.map((x: ImportType) => ({
                    value: x.key,
                    label: x.name,
                  }))}
                  onChange={(value) => {
                    setType(value);
                    setFile(undefined);
                  }}
                />
              </Form.Item>
              {r.scope === 'platform' && (
                <>
                  <Form.Item label="目标物业公司" required>
                    <Select
                      showSearch
                      optionFilterProp="label"
                      loading={companies.isLoading}
                      value={companyId || undefined}
                      onChange={(value) => {
                        setCompanyId(value);
                        setTarget('');
                      }}
                      options={companies.data?.map((x) => ({
                        value: x.id,
                        label: x.name,
                      }))}
                    />
                  </Form.Item>
                  {selected && selected.allowed_scope_types.length > 1 && (
                    <Form.Item label="范围类型">
                      <Select
                        value={scopeType}
                        onChange={setScopeType}
                        options={selected.allowed_scope_types.map((x) => ({
                          value: x,
                          label: x === 'community' ? '小区' : '公司',
                        }))}
                      />
                    </Form.Item>
                  )}
                  {scopeType === 'community' && (
                    <Form.Item label="目标小区" required>
                      <Select
                        showSearch
                        optionFilterProp="label"
                        value={target || undefined}
                        loading={communities.isLoading}
                        onChange={setTarget}
                        options={communities.data?.map((x) => ({
                          value: x.id,
                          label: x.name,
                        }))}
                      />
                    </Form.Item>
                  )}
                </>
              )}
              <Form.Item label="模板版本">
                <Select
                  value={version}
                  onChange={setVersion}
                  options={selected?.versions
                    .filter((v) => v.available_for_new_batches)
                    .map((v) => ({
                      value: v.version_no,
                      label: `v${v.version_no}`,
                    }))}
                />
              </Form.Item>
              <DetailGrid
                items={[
                  [
                    '所属公司',
                    r.scope === 'property'
                      ? company.data?.name || '读取中'
                      : companies.data?.find((x) => x.id === companyId)?.name ||
                        '请选择',
                  ],
                  ['目标范围', targetName || '请选择小区'],
                  ['导入模式', '仅创建，不覆盖已有数据'],
                  ['模板版本', version ? `v${version} · 严格版本模板` : '—'],
                ]}
              />
              <Alert
                type="info"
                showIcon
                title={`导入范围：${targetName || '尚未选择'}`}
                description="创建批次后范围、模板和模式即锁定。需要导入其他小区，请返回后切换业务上下文。"
                style={{ margin: '20px 0' }}
              />
              <Button
                type="primary"
                disabled={!targetId || !version || !r.can('upload')}
                onClick={() => setStep(1)}
              >
                下一步：准备文件 <ArrowRightOutlined />
              </Button>
            </Form>
          )}
          {step === 1 && (
            <Space orientation="vertical" size={20} style={{ width: '100%' }}>
              <Alert
                type="warning"
                showIcon
                title={
                  notices[type] ||
                  template.data?.release_notes ||
                  '请核对目标范围和模板要求。'
                }
              />
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: 20,
                  background: '#f7f9fc',
                  borderRadius: 10,
                }}
              >
                <Space>
                  <FileExcelOutlined
                    style={{ fontSize: 32, color: '#3155cf' }}
                  />
                  <div>
                    <strong>
                      {selected?.name} · 模板 v{version}
                    </strong>
                    <div style={{ marginTop: 5, color: '#64748b' }}>
                      保留原始列名；必填位置须完整填写
                    </div>
                  </div>
                </Space>
                <Button
                  icon={<DownloadOutlined />}
                  disabled={
                    !selected?.versions.find((x) => x.version_no === version)
                      ?.template_downloadable
                  }
                  onClick={() => {
                    void r.api
                      .templateDownload(type, version!)
                      .then(saveFile)
                      .catch(setError);
                  }}
                >
                  下载模板
                </Button>
              </div>
              <ErrorNotice error={template.error} />
              <Upload.Dragger
                accept=".csv,.xlsx"
                maxCount={1}
                disabled={!r.can('upload')}
                beforeUpload={(next) => {
                  if (
                    !/\.(csv|xlsx)$/i.test(next.name) ||
                    !next.size ||
                    next.size > 10485760
                  ) {
                    message.error('请选择不超过 10 MiB 的非空 CSV 或 XLSX');
                    return Upload.LIST_IGNORE;
                  }
                  setFile(next);
                  return false;
                }}
                fileList={
                  file
                    ? [{ uid: 'source', name: file.name, status: 'done' }]
                    : []
                }
                onRemove={() => {
                  setFile(undefined);
                }}
              >
                <CloudUploadOutlined
                  style={{ fontSize: 36, color: '#3155cf', margin: 10 }}
                />
                <p>
                  <strong>拖拽文件到此处，或点击选择</strong>
                </p>
                <p>CSV / XLSX · 最大 10 MiB · 50,000 数据行 · 200 列</p>
              </Upload.Dragger>
              {template.data && (
                <Table
                  rowKey="key"
                  size="small"
                  pagination={false}
                  dataSource={template.data.fields}
                  columns={[
                    { title: '模板字段', dataIndex: 'label' },
                    {
                      title: '是否必填',
                      dataIndex: 'required',
                      render: (value) => (value ? '必填' : '选填'),
                    },
                    { title: '填写要求', dataIndex: 'description' },
                    {
                      title: '示例',
                      dataIndex: 'example',
                      render: (value) => String(value ?? '—'),
                    },
                  ]}
                />
              )}
              <Space>
                <Button onClick={() => setStep(0)}>上一步</Button>
                <Button
                  type="primary"
                  disabled={!file}
                  onClick={() => void submit()}
                >
                  创建草稿并预检
                </Button>
              </Space>
            </Space>
          )}
          {step === 2 && (
            <div style={{ padding: '44px 20px', textAlign: 'center' }}>
              {busy && <Spin size="large" />}
              {uploadTotal !== null && uploadTotal > 0 && uploaded !== null && (
                <Progress
                  style={{ maxWidth: 420, margin: '20px auto' }}
                  percent={Math.min(
                    100,
                    Math.floor((uploaded / uploadTotal) * 100),
                  )}
                />
              )}
              <h3>
                {busy
                  ? '正在接收文件，后续解析与预检由任务处理'
                  : '上传尚未完成'}
              </h3>
              <p style={{ color: '#64748b' }}>
                范围：{targetName} · {file?.name} · 确认前不会创建业务数据
              </p>
              {unknownResult && (
                <Alert
                  type="warning"
                  showIcon
                  title="请求结果待核实"
                  description="请先查看原批次或导入历史。确认原草稿仍待上传时，可使用保留的原幂等键重试同一文件。"
                />
              )}
              {!busy && (
                <Space style={{ marginTop: 20 }}>
                  {draft && (
                    <Button onClick={() => go('import-detail', { id: draft })}>
                      核实原批次
                    </Button>
                  )}
                  <Button onClick={() => go('imports')}>查看导入历史</Button>
                  <Button type="primary" onClick={() => void submit()}>
                    使用原请求重试
                  </Button>
                </Space>
              )}
            </div>
          )}
        </Panel>
      )}
    </>
  );
}
