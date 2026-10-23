import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from '@umijs/max';
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Select,
  Space,
  Table,
  Typography,
} from 'antd';
import { useState } from 'react';
import { OperationError, ReadError } from '../../components/AdminFeedback';
import { useAdminApp } from '../admin-app-context';
import { saveDownload } from './api';
import { useImports, useImportWrite } from './runtime';
import { cell, time } from './values';
import type { BatchCreate, ScopeType, TemplateField } from './types';
export function ImportsNewPage() {
  const runtime = useImports(),
    { api, can } = runtime,
    nav = useAdminApp(),
    navigate = useNavigate(),
    [params] = useSearchParams();
  const [typeKey, setTypeKey] = useState(params.get('import_type') || ''),
    [companyId, setCompanyId] = useState(
      params.get('scope_type') === 'company'
        ? params.get('scope_id') || ''
        : params.get('property_company_id') || '',
    ),
    [scopeType, setScopeType] = useState<ScopeType>(
      params.get('scope_type') === 'community' ? 'community' : 'company',
    ),
    [scopeId, setScopeId] = useState(params.get('scope_id') || ''),
    [version, setVersion] = useState<number>(),
    [companySearch, setCompanySearch] = useState(''),
    [communitySearch, setCommunitySearch] = useState(''),
    [downloadError, setDownloadError] = useState<unknown>(null);
  const locked = !!(
    params.get('import_type') &&
    params.get('scope_type') &&
    params.get('scope_id')
  );
  const types = useQuery({
    queryKey: ['imports', 'types'],
    queryFn: ({ signal }) => api.types(signal),
    enabled: can('create'),
  });
  const type = types.data?.items.find((item) => item.key === typeKey),
    selectedVersion =
      version ||
      type?.versions.find((item) => item.available_for_new_batches)?.version_no;
  const template = useQuery({
    queryKey: ['imports', 'template', typeKey, selectedVersion],
    queryFn: ({ signal }) => api.template(typeKey, selectedVersion!, signal),
    enabled: !!type && !!selectedVersion && can('create'),
  });
  const current = useQuery({
    queryKey: ['imports', 'current-company'],
    queryFn: runtime.currentCompany,
    enabled: !!runtime.currentCompany && !!type,
  });
  const companies = useQuery({
    queryKey: ['imports', 'scope-companies', companySearch],
    queryFn: () =>
      runtime.companies({
        page: 1,
        page_size: 100,
        name: companySearch || undefined,
      }),
    enabled: runtime.scope === 'platform_admin' && !!type,
  });
  const targetCompanyId =
    runtime.scope === 'platform_admin' ? companyId : current.data?.id;
  const communities = useQuery({
    queryKey: [
      'imports',
      'scope-communities',
      targetCompanyId,
      communitySearch,
    ],
    queryFn: () =>
      runtime.communities({
        page: 1,
        page_size: 100,
        property_company_id:
          runtime.scope === 'platform_admin' ? targetCompanyId : undefined,
        name: communitySearch || undefined,
      }),
    enabled:
      !!type && !!targetCompanyId && scopeType === 'community' && !locked,
  });
  const lockedCommunity = useQuery({
    queryKey: ['imports', 'scope-community', scopeId],
    queryFn: () => runtime.community(scopeId),
    enabled: locked && !!type && scopeType === 'community' && !!scopeId,
  });
  const scopeName =
    scopeType === 'company'
      ? [
          ...(companies.data?.items || []),
          ...(current.data ? [current.data] : []),
        ].find((item) => item.id === targetCompanyId)?.name
      : locked
        ? lockedCommunity.data?.name
        : communities.data?.items.find((item) => item.id === scopeId)?.name;
  const destination = runtime.businessDestination?.(typeKey, {
    type: scopeType,
    id: scopeId,
  });
  const write = useImportWrite('new');
  async function create() {
    if (!type || !targetCompanyId || !selectedVersion || !scopeName) return;
    const body: BatchCreate = {
      import_type: typeKey,
      template_version_no: selectedVersion,
      scope: {
        type: scopeType,
        id: scopeType === 'company' ? targetCompanyId : scopeId,
      },
      mode: 'create',
      ...(runtime.scope === 'platform_admin'
        ? { property_company_id: targetCompanyId }
        : {}),
    };
    const result = await write.run('create', body, (key, original) =>
      api.create(original as BatchCreate, key),
    );
    if (result) navigate(nav.path(`${runtime.pageRoot}/${result.batch_id}`));
  }
  return (
    <PageContainer title="新建导入">
      <Space orientation="vertical" style={{ width: '100%' }}>
        <OperationError error={write.error || downloadError} />
        {write.pending.length > 0 && (
          <Alert
            type="warning"
            title="提交结果正在核实，请勿重复点击"
            description={
              <Button
                loading={write.busy}
                onClick={() =>
                  void write
                    .run('create', undefined, (key, body) =>
                      api.create(body as BatchCreate, key),
                    )
                    .then((result) => {
                      if (result)
                        navigate(
                          nav.path(`${runtime.pageRoot}/${result.batch_id}`),
                        );
                    })
                }
              >
                使用原请求核实草稿
              </Button>
            }
          />
        )}
        {types.isError ? (
          <ReadError error={types.error} retry={() => void types.refetch()} />
        ) : types.data?.items.length === 0 ? (
          <Empty description="尚无可用导入类型" />
        ) : (
          <Card loading={types.isLoading}>
            <Form layout="vertical">
              <Form.Item label="导入类型">
                <Select
                  aria-label="导入类型"
                  disabled={locked || write.busy}
                  value={typeKey || undefined}
                  options={types.data?.items.map((item) => ({
                    value: item.key,
                    label: item.name,
                  }))}
                  onChange={(key) => {
                    setTypeKey(key);
                    setVersion(undefined);
                    setScopeId('');
                    setCompanyId('');
                    const next = types.data?.items.find(
                      (item) => item.key === key,
                    );
                    setScopeType(next?.allowed_scope_types[0] || 'company');
                  }}
                />
              </Form.Item>
              {type && (
                <>
                  <Form.Item label="目标公司">
                    {runtime.scope === 'platform_admin' ? (
                      <Select
                        aria-label="目标公司"
                        disabled={locked && scopeType === 'company'}
                        showSearch
                        filterOption={false}
                        onSearch={setCompanySearch}
                        value={companyId || undefined}
                        onChange={(id) => {
                          setCompanyId(id);
                          setScopeId('');
                        }}
                        loading={companies.isFetching}
                        options={companies.data?.items.map((item) => ({
                          value: item.id,
                          label: item.name,
                        }))}
                      />
                    ) : (
                      <Typography.Text>
                        {current.data?.name || '正在读取所属公司'}（不可切换）
                      </Typography.Text>
                    )}
                  </Form.Item>
                  <Form.Item label="范围类型">
                    <Select
                      aria-label="范围类型"
                      disabled={locked}
                      value={scopeType}
                      options={type.allowed_scope_types.map((value) => ({
                        value,
                        label: value === 'company' ? '公司' : '小区',
                      }))}
                      onChange={(value) => {
                        setScopeType(value);
                        setScopeId('');
                      }}
                    />
                  </Form.Item>
                  {scopeType === 'community' && (
                    <Form.Item label="导入小区">
                      <Select
                        aria-label="导入小区"
                        disabled={locked}
                        showSearch
                        filterOption={false}
                        onSearch={setCommunitySearch}
                        value={scopeId || undefined}
                        onChange={setScopeId}
                        options={(lockedCommunity.data
                          ? [lockedCommunity.data]
                          : communities.data?.items || []
                        ).map((item) => ({
                          value: item.id,
                          label: item.name,
                        }))}
                        loading={communities.isFetching}
                      />
                    </Form.Item>
                  )}
                  <Form.Item label="模板版本">
                    <Select
                      aria-label="模板版本"
                      value={selectedVersion}
                      onChange={setVersion}
                      options={type.versions.map((item) => ({
                        value: item.version_no,
                        label: `v${item.version_no}${item.available_for_new_batches ? '' : '（停止用于新批次）'}`,
                        disabled: !item.available_for_new_batches,
                      }))}
                    />
                  </Form.Item>
                </>
              )}
              {scopeName && (
                <Alert
                  type="info"
                  title={`范围已锁定：${scopeName}`}
                  description={
                    <>
                      导入文件中的数据将仅处理到当前范围。批次创建后范围、模板和模式不可修改。
                      {locked && destination && (
                        <div>来源页面：{destination.label}</div>
                      )}
                    </>
                  }
                />
              )}
              {companies.isError && (
                <ReadError
                  error={companies.error}
                  retry={() => void companies.refetch()}
                />
              )}
              {current.isError && (
                <ReadError
                  error={current.error}
                  retry={() => void current.refetch()}
                />
              )}
              {communities.isError && (
                <ReadError
                  error={communities.error}
                  retry={() => void communities.refetch()}
                />
              )}
              {lockedCommunity.isError && (
                <ReadError
                  error={lockedCommunity.error}
                  retry={() => void lockedCommunity.refetch()}
                />
              )}
              {template.isError && (
                <ReadError
                  error={template.error}
                  retry={() => void template.refetch()}
                />
              )}
              {template.data && (
                <Card
                  title={`${template.data.name} · v${template.data.version_no}`}
                  extra={
                    type?.versions.find(
                      (item) => item.version_no === selectedVersion,
                    )?.template_downloadable && (
                      <Button
                        onClick={() => {
                          setDownloadError(null);
                          void api
                            .templateDownload(typeKey, selectedVersion!)
                            .then(saveDownload)
                            .catch(setDownloadError);
                        }}
                      >
                        下载模板
                      </Button>
                    )
                  }
                >
                  <Typography.Paragraph>
                    发布时间：{time(template.data.released_at)} ·{' '}
                    {template.data.release_notes}
                  </Typography.Paragraph>
                  <Table<TemplateField>
                    rowKey="key"
                    pagination={false}
                    scroll={{ x: 1200 }}
                    dataSource={[...template.data.fields].sort(
                      (a, b) => a.order - b.order,
                    )}
                    columns={[
                      { title: '顺序', dataIndex: 'order' },
                      { title: '字段编码', dataIndex: 'key' },
                      { title: '列名', dataIndex: 'label' },
                      {
                        title: '必填',
                        dataIndex: 'required',
                        render: (v: boolean) => (v ? '是' : '否'),
                      },
                      { title: '数据类型', dataIndex: 'data_type' },
                      {
                        title: '最大长度',
                        dataIndex: 'max_length',
                        render: cell,
                      },
                      { title: '格式', dataIndex: 'format', render: cell },
                      {
                        title: '枚举',
                        dataIndex: 'enum_values',
                        render: (v: unknown[]) => v.map(cell).join('、'),
                      },
                      { title: '示例', dataIndex: 'example', render: cell },
                      { title: '业务说明', dataIndex: 'description' },
                      {
                        title: '规范化',
                        dataIndex: 'normalization_rules',
                        render: (v: string[]) => v.join('；'),
                      },
                    ]}
                  />
                </Card>
              )}
              <Button
                type="primary"
                loading={write.busy}
                disabled={
                  !can('create') ||
                  !scopeName ||
                  !template.data?.available_for_new_batches ||
                  !type?.allowed_scope_types.includes(scopeType) ||
                  write.pending.length > 0
                }
                onClick={() => void create()}
              >
                创建草稿，下一步上传文件
              </Button>
            </Form>
          </Card>
        )}
      </Space>
    </PageContainer>
  );
}
