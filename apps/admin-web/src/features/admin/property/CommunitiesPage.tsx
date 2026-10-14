import { useState } from 'react';
import { Link } from '@umijs/max';
import {
  PageContainer,
  ProTable,
  type ProColumns,
} from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { App, Button, Space, Tag } from 'antd';
import { useAdminSession } from '../../../auth/use-admin-session';
import { adminPath } from '../../../app/admin-routes';
import {
  ListEmpty,
  OperationError,
  ReadError,
} from '../../../components/AdminFeedback';
import type {
  Community,
  PropertyCompany,
} from '../../../shared/admin-api/property';
import { useListState } from '../hooks';
import { parseEnabled, usePropertyApi, usePropertyOperation } from './hooks';
import CommunityDrawer from './CommunityDrawer';
import { ResourceSearch } from './ResourceSearch';

export function CommunityList({ company }: { company?: PropertyCompany }) {
  const api = usePropertyApi(),
    state = useListState(company ? 'communities_' : '');
  const { status, hasPermission } = useAdminSession();
  const { modal } = App.useApp();
  const [editor, setEditor] = useState<{ id?: string } | null>(null);
  const operation = usePropertyOperation();
  const filters = {
    page: state.page,
    page_size: state.pageSize,
    name: state.params.get('name') || undefined,
    code: state.params.get('code') || undefined,
    enabled: parseEnabled(state.params.get('enabled')),
    property_company_id:
      company?.id ?? (state.params.get('property_company_id') || undefined),
  };
  const query = useQuery({
    queryKey: ['communities', 'list', filters],
    queryFn: () => api.communities(filters),
    enabled:
      status === 'authenticated' && hasPermission('property.community.read'),
  });
  const columns: ProColumns<Community>[] = [
    { title: '小区编码', dataIndex: 'code' },
    { title: '小区名称', dataIndex: 'name' },
    ...(!company
      ? [
          {
            title: '物业公司',
            dataIndex: 'property_company_name',
            render: (_: unknown, row: Community) =>
              hasPermission('property.company.read') ? (
                <Link
                  to={adminPath(
                    'platform_admin',
                    `/platform/property/companies/${row.property_company_id}`,
                  )}
                >
                  {row.property_company_name}
                </Link>
              ) : (
                row.property_company_name
              ),
          },
        ]
      : []),
    { title: '地址', dataIndex: 'address' },
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
      width: 180,
      render: (_, row) =>
        hasPermission('property.community.update') && (
          <Space wrap>
            <Button
              type="link"
              disabled={operation.isPending}
              onClick={() => setEditor({ id: row.id })}
            >
              编辑
            </Button>
            <Button
              type="link"
              danger={row.enabled}
              disabled={operation.isPending}
              onClick={() =>
                modal.confirm({
                  title: `${row.enabled ? '停用' : '启用'} ${row.name}？`,
                  content: row.enabled
                    ? '停用后保留历史查询，阻止该小区新增业务。其他小区不受影响。'
                    : '恢复该小区的业务接入资格，所属公司也须启用。',
                  onOk: () =>
                    operation
                      .mutateAsync({
                        run: () =>
                          api.updateCommunity(row.id, {
                            enabled: !row.enabled,
                          }),
                      })
                      .then(() => undefined),
                })
              }
            >
              {row.enabled ? '停用' : '启用'}
            </Button>
          </Space>
        ),
    },
  ];
  return (
    <>
      <OperationError error={operation.error} />
      <ResourceSearch
        values={filters}
        companyFilter={!company}
        submit={(values) => state.update({ ...values, page: 1 })}
        reset={() =>
          state.update({
            name: undefined,
            code: undefined,
            enabled: undefined,
            property_company_id: undefined,
            page: 1,
          })
        }
      />
      {query.isError && (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      )}
      <ProTable<Community>
        headerTitle={company ? '关联小区' : undefined}
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
                filters.enabled !== undefined ||
                (!company && !!filters.property_company_id)
              }
            />
          ),
        }}
        toolBarRender={() =>
          hasPermission('property.community.create')
            ? [
                <Button
                  key="create"
                  type="primary"
                  onClick={() => setEditor({})}
                >
                  创建小区
                </Button>,
              ]
            : []
        }
      />
      {editor && (
        <CommunityDrawer
          key={editor.id ?? 'new'}
          id={editor.id}
          company={company}
          done={() => setEditor(null)}
        />
      )}
    </>
  );
}

export default function CommunitiesPage() {
  return (
    <PageContainer title="小区管理">
      <CommunityList />
    </PageContainer>
  );
}
