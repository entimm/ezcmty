import { useState } from 'react';
import { Link } from '@umijs/max';
import {
  PageContainer,
  ProTable,
  type ProColumns,
} from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Button, Space, Tag } from 'antd';
import { usePlatformSession } from '../hooks';
import { useAdminApp } from '../../../shared/admin-app-context';
import {
  ListEmpty,
  OperationError,
  ReadError,
} from '../../../components/AdminFeedback';
import type { PropertyCompany } from '../../../shared/api/property';
import { useListState } from '../../../shared/hooks/use-list-state';
import { parseEnabled } from '../../../shared/filters';
import {
  usePropertyOnboardingApi,
  usePropertyOnboardingOperation,
} from './hooks';
import CompanyDrawer from './CompanyDrawer';
import { CompanyActions } from './CompanyActions';
import { ResourceSearch } from '../../../components/ResourceSearch';

export default function CompaniesPage() {
  const { path } = useAdminApp();
  const api = usePropertyOnboardingApi(),
    state = useListState();
  const { status, hasPermission } = usePlatformSession();
  const [editor, setEditor] = useState<{ id?: string } | null>(null);
  const operation = usePropertyOnboardingOperation();
  const filters = {
    page: state.page,
    page_size: state.pageSize,
    name: state.params.get('name') || undefined,
    code: state.params.get('code') || undefined,
    enabled: parseEnabled(state.params.get('enabled')),
  };
  const query = useQuery({
    queryKey: ['property-companies', 'list', filters],
    queryFn: () => api.companies(filters),
    enabled:
      status === 'authenticated' && hasPermission('property.company.read'),
  });
  const columns: ProColumns<PropertyCompany>[] = [
    { title: '公司编码', dataIndex: 'code' },
    { title: '公司名称', dataIndex: 'name' },
    { title: '联系人', dataIndex: 'contact_name' },
    { title: '联系电话', dataIndex: 'contact_phone' },
    {
      title: '状态',
      dataIndex: 'enabled',
      render: (_, row) => (
        <Tag color={row.enabled ? 'green' : undefined}>
          {row.enabled ? '启用' : '停用'}
        </Tag>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      render: (_, row) => new Date(row.created_at).toLocaleString(),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 220,
      render: (_, row) => (
        <Space wrap>
          <Link to={path(`/platform/property/companies/${row.id}`)}>详情</Link>
          <CompanyActions
            company={row}
            onEdit={() => setEditor({ id: row.id })}
            operation={operation}
          />
        </Space>
      ),
    },
  ];
  return (
    <PageContainer title="物业公司">
      <OperationError error={operation.error} />
      <ResourceSearch
        values={filters}
        submit={(values) => state.update({ ...values, page: 1 })}
        reset={() =>
          state.update({
            name: undefined,
            code: undefined,
            enabled: undefined,
            page: 1,
          })
        }
      />
      {query.isError && (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      )}
      <ProTable<PropertyCompany>
        rowKey="id"
        columns={columns}
        search={false}
        dataSource={query.data?.items ?? []}
        loading={query.isFetching}
        pagination={{ ...state.pagination, total: query.data?.total ?? 0 }}
        scroll={{ x: 1100 }}
        options={{
          reload: () => void query.refetch(),
          density: true,
          setting: true,
        }}
        locale={{
          emptyText: (
            <ListEmpty
              filtered={
                !!filters.name ||
                !!filters.code ||
                filters.enabled !== undefined
              }
            />
          ),
        }}
        toolBarRender={() =>
          hasPermission('property.company.create')
            ? [
                <Button
                  key="create"
                  type="primary"
                  onClick={() => setEditor({})}
                >
                  创建物业公司
                </Button>,
              ]
            : []
        }
      />
      {editor && (
        <CompanyDrawer
          key={editor.id ?? 'new'}
          id={editor.id}
          done={() => setEditor(null)}
        />
      )}
    </PageContainer>
  );
}
