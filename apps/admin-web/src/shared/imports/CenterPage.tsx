import { PageContainer } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from '@umijs/max';
import { Alert, Button, Card, Form, Input, Select, Space, Table } from 'antd';
import { ReadError } from '../../components/AdminFeedback';
import { useAdminApp } from '../admin-app-context';
import { useListState } from '../hooks/use-list-state';
import { useImports, isActive } from './runtime';
import { BatchStatusTag } from './presentation';
import { statusNames, time } from './values';
import type { Batch, BatchStatus, Filters } from './types';
export function ImportsCenterPage() {
  const { api, can, pageRoot } = useImports(),
    navigation = useAdminApp(),
    navigate = useNavigate(),
    list = useListState();
  const filters: Filters = { page: list.page, page_size: list.pageSize };
  for (const key of [
    'import_type',
    'scope_type',
    'scope_id',
    'status',
    'created_by',
    'created_from',
    'created_before',
    'sort',
  ])
    filters[key] = list.params.get(key) || undefined;
  if (list.params.has('has_errors'))
    filters.has_errors = list.params.get('has_errors') === 'true';
  const types = useQuery({
    queryKey: ['imports', 'types'],
    queryFn: ({ signal }) => api.types(signal),
    enabled: can('create'),
  });
  const query = useQuery({
    queryKey: ['imports', 'batches', filters],
    queryFn: ({ signal }) => api.batches(filters, signal),
    enabled: can('read'),
    refetchInterval: (query) =>
      query.state.data?.items.some(isActive) ? 5000 : false,
  });
  return (
    <PageContainer
      title="导入中心"
      extra={
        <Button
          type="primary"
          disabled={!can('create') || !types.data?.items.length}
          onClick={() => navigate(navigation.path(`${pageRoot}/new`))}
        >
          新建导入
        </Button>
      }
    >
      <Space orientation="vertical" style={{ width: '100%' }}>
        {types.data?.items.length === 0 && (
          <Alert title="尚无可用导入类型" type="info" showIcon />
        )}
        {types.isError && (
          <ReadError error={types.error} retry={() => void types.refetch()} />
        )}
        <Card>
          <Form
            layout="inline"
            initialValues={Object.fromEntries(list.params)}
            onFinish={(values: Record<string, string>) =>
              list.update({ ...values, page: 1 })
            }
          >
            <Form.Item label="导入类型" name="import_type">
              <Input style={{ width: 140 }} allowClear />
            </Form.Item>
            <Form.Item label="范围类型" name="scope_type">
              <Select
                allowClear
                style={{ width: 110 }}
                options={[
                  { value: 'company', label: '公司' },
                  { value: 'community', label: '小区' },
                ]}
              />
            </Form.Item>
            <Form.Item label="范围 ID" name="scope_id">
              <Input allowClear />
            </Form.Item>
            <Form.Item label="状态" name="status">
              <Select
                allowClear
                style={{ width: 160 }}
                options={Object.entries(statusNames).map(([value, label]) => ({
                  value,
                  label,
                }))}
              />
            </Form.Item>
            <Form.Item label="创建人 ID" name="created_by">
              <Input allowClear />
            </Form.Item>
            <Form.Item label="有无错误" name="has_errors">
              <Select
                allowClear
                style={{ width: 100 }}
                options={[
                  { value: 'true', label: '有错误' },
                  { value: 'false', label: '无错误' },
                ]}
              />
            </Form.Item>
            <Form.Item label="创建时间起（含时区）" name="created_from">
              <Input placeholder="2026-10-01T00:00:00Z" allowClear />
            </Form.Item>
            <Form.Item label="创建时间止（不含）" name="created_before">
              <Input placeholder="2026-11-01T00:00:00Z" allowClear />
            </Form.Item>
            <Form.Item label="排序" name="sort">
              <Select
                style={{ width: 160 }}
                options={[
                  { value: '-created_at,-id', label: '最新创建' },
                  { value: 'created_at,id', label: '最早创建' },
                  { value: '-updated_at,-id', label: '最近更新' },
                  { value: 'updated_at,id', label: '最早更新' },
                ]}
              />
            </Form.Item>
            <Button htmlType="submit">查询</Button>
          </Form>
        </Card>
        {query.isError ? (
          <ReadError error={query.error} retry={() => void query.refetch()} />
        ) : (
          <Table<Batch>
            rowKey="id"
            loading={query.isLoading}
            dataSource={query.data?.items}
            pagination={{ ...list.pagination, total: query.data?.total }}
            scroll={{ x: 1500 }}
            locale={{ emptyText: '暂无导入记录' }}
            columns={[
              {
                title: '导入类型',
                dataIndex: 'import_type_name',
                render: (value: string, row) => (
                  <Link to={navigation.path(`${pageRoot}/${row.id}`)}>
                    {value}
                  </Link>
                ),
              },
              {
                title: '范围',
                render: (_, row) => `${row.scope.name}（范围已锁定）`,
              },
              {
                title: '模板版本',
                render: (_, row) => `v${row.template.version_no}`,
              },
              {
                title: '文件名',
                render: (_, row) => row.source_artifact?.file_name || '—',
              },
              { title: '创建人', render: (_, row) => row.created_by.name },
              {
                title: '状态',
                dataIndex: 'status',
                render: (status: BatchStatus) => (
                  <BatchStatusTag status={status} />
                ),
              },
              {
                title: '总行数',
                render: (_, row) =>
                  row.source_artifact && row.preview
                    ? row.statistics.total_rows
                    : '未知',
              },
              {
                title: '成功',
                render: (_, row) => row.statistics.execution.created_rows,
              },
              {
                title: '失败',
                render: (_, row) => row.statistics.execution.failed_rows,
              },
              { title: '创建时间', dataIndex: 'created_at', render: time },
              { title: '最近更新', dataIndex: 'updated_at', render: time },
            ]}
          />
        )}
      </Space>
    </PageContainer>
  );
}
