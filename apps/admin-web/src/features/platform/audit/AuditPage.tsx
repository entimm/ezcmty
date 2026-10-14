import { useState } from 'react';
import {
  PageContainer,
  ProTable,
  type ProColumns,
} from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import {
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd';
import { usePlatformSession } from '../hooks';
import type { Audit } from '../../../shared/api/admin';
import { usePlatformAdminApi } from '../hooks';
import { useListState } from '../../../shared/hooks/use-list-state';
import { ListEmpty, ReadError } from '../../../components/AdminFeedback';

export default function AuditPage() {
  const api = usePlatformAdminApi(),
    state = useListState(),
    { status, hasPermission } = usePlatformSession();
  const [selected, setSelected] = useState<Audit | null>(null);
  const filters = {
    page: state.page,
    page_size: state.pageSize,
    action: state.params.get('action') || undefined,
    result: ['success', 'failure'].includes(state.params.get('result') || '')
      ? state.params.get('result')!
      : undefined,
    request_id: state.params.get('request_id') || undefined,
    from_time: state.params.get('from_time') || undefined,
    to_time: state.params.get('to_time') || undefined,
  };
  const query = useQuery({
    queryKey: ['audit', filters],
    queryFn: () => api.audit(filters),
    enabled: status === 'authenticated' && hasPermission('admin.audit.read'),
  });
  const columns: ProColumns<Audit>[] = [
    {
      title: '操作时间',
      dataIndex: 'created_at',
      render: (_, row) => new Date(row.created_at).toLocaleString(),
    },
    { title: '操作者', render: (_, row) => row.actor_name || '系统 / 匿名' },
    { title: '操作', dataIndex: 'action' },
    {
      title: '目标',
      render: (_, row) => `${row.target_type} · ${row.target_id || '—'}`,
    },
    {
      title: '结果',
      render: (_, row) => (
        <Tag color={row.result === 'success' ? 'green' : 'red'}>
          {row.result === 'success' ? '成功' : '失败'}
        </Tag>
      ),
    },
    { title: '请求标识', dataIndex: 'request_id', ellipsis: true },
    {
      title: '操作',
      valueType: 'option',
      render: (_, row) => (
        <Button type="link" onClick={() => setSelected(row)}>
          详情
        </Button>
      ),
    },
  ];
  const localTime = (value?: string) => {
    if (!value) return '';
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return '';
    const offset = date.getTimezoneOffset() * 60000;
    return new Date(date.getTime() - offset).toISOString().slice(0, 16);
  };
  return (
    <PageContainer title="审计日志">
      <Typography.Paragraph type="secondary">
        显示时区：{Intl.DateTimeFormat().resolvedOptions().timeZone}，时间查询按
        UTC 提交。
      </Typography.Paragraph>
      <Form
        key={JSON.stringify(filters)}
        layout="inline"
        style={{ marginBottom: 16, rowGap: 12 }}
        initialValues={{
          ...filters,
          from_time: localTime(filters.from_time),
          to_time: localTime(filters.to_time),
        }}
        onFinish={(values: {
          action?: string;
          result?: string;
          request_id?: string;
          from_time?: string;
          to_time?: string;
        }) =>
          state.update({
            ...values,
            from_time: values.from_time
              ? new Date(values.from_time).toISOString()
              : undefined,
            to_time: values.to_time
              ? new Date(values.to_time).toISOString()
              : undefined,
            page: 1,
          })
        }
      >
        <Form.Item name="from_time" label="开始时间">
          <Input type="datetime-local" />
        </Form.Item>
        <Form.Item name="to_time" label="结束时间">
          <Input type="datetime-local" />
        </Form.Item>
        <Form.Item name="action" label="操作类型">
          <Input allowClear />
        </Form.Item>
        <Form.Item name="result" label="结果">
          <Select
            allowClear
            style={{ width: 100 }}
            options={[
              { value: 'success', label: '成功' },
              { value: 'failure', label: '失败' },
            ]}
          />
        </Form.Item>
        <Form.Item name="request_id" label="请求标识">
          <Input allowClear />
        </Form.Item>
        <Space>
          <Button type="primary" htmlType="submit">
            查询
          </Button>
          <Button
            onClick={() =>
              state.update({
                action: undefined,
                result: undefined,
                request_id: undefined,
                from_time: undefined,
                to_time: undefined,
                page: 1,
              })
            }
          >
            重置
          </Button>
        </Space>
      </Form>
      {query.isError && (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      )}
      <ProTable<Audit>
        rowKey="id"
        columns={columns}
        search={false}
        dataSource={query.data?.items ?? []}
        loading={query.isFetching}
        pagination={{ ...state.pagination, total: query.data?.total ?? 0 }}
        scroll={{ x: 1200 }}
        options={{ reload: () => void query.refetch() }}
        locale={{
          emptyText: (
            <ListEmpty
              filtered={Object.entries(filters).some(
                ([key, value]) =>
                  !['page', 'page_size'].includes(key) && value !== undefined,
              )}
            />
          ),
        }}
      />
      <Drawer
        open={!!selected}
        title="审计详情"
        size={560}
        destroyOnHidden
        onClose={() => setSelected(null)}
      >
        {selected && (
          <Descriptions
            column={1}
            items={[
              {
                key: 'time',
                label: '操作时间',
                children: new Date(selected.created_at).toLocaleString(),
              },
              {
                key: 'actor',
                label: '操作者',
                children: selected.actor_name || '系统 / 匿名',
              },
              {
                key: 'company',
                label: '关联公司',
                children: selected.property_company_id || '—',
              },
              { key: 'action', label: '操作', children: selected.action },
              {
                key: 'target',
                label: '目标',
                children: selected.target_id || '—',
              },
              {
                key: 'result',
                label: '结果',
                children: selected.result === 'success' ? '成功' : '失败',
              },
              {
                key: 'request',
                label: '请求标识',
                children: (
                  <Typography.Text copyable>
                    {selected.request_id}
                  </Typography.Text>
                ),
              },
              {
                key: 'metadata',
                label: '操作信息',
                children: (
                  <pre
                    style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}
                  >
                    {JSON.stringify(selected.metadata, null, 2)}
                  </pre>
                ),
              },
            ]}
          />
        )}
      </Drawer>
    </PageContainer>
  );
}
