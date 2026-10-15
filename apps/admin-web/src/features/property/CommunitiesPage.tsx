import { useState } from 'react';
import { Link } from '@umijs/max';
import {
  PageContainer,
  ProTable,
  type ProColumns,
} from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Button, Descriptions, Drawer, Skeleton, Tag } from 'antd';

import { usePropertySession } from './hooks';
import { ListEmpty, ReadError } from '../../components/AdminFeedback';
import type { Community } from '../../shared/api/property';
import { useListState } from '../../shared/hooks/use-list-state';
import { parseEnabled } from '../../shared/filters';
import { usePropertyWorkspaceApi } from './hooks';
import { ResourceSearch } from '../../components/ResourceSearch';
import { useAdminApp } from '../../shared/admin-app-context';

function CommunityDetails({ id, close }: { id: string; close: () => void }) {
  const api = usePropertyWorkspaceApi();
  const { status, hasPermission } = usePropertySession();
  const detail = useQuery({
    queryKey: ['communities', 'detail', id],
    queryFn: () => api.community(id),
    enabled:
      status === 'authenticated' && hasPermission('property.community.read'),
  });
  return (
    <Drawer title="小区详情" open size={560} onClose={close} destroyOnHidden>
      {detail.isError ? (
        <ReadError error={detail.error} retry={() => void detail.refetch()} />
      ) : detail.data ? (
        <Descriptions
          column={1}
          items={[
            { key: 'name', label: '小区名称', children: detail.data.name },
            { key: 'code', label: '小区编码', children: detail.data.code },
            {
              key: 'company',
              label: '物业公司',
              children: detail.data.property_company_name,
            },
            { key: 'address', label: '地址', children: detail.data.address },
            {
              key: 'enabled',
              label: '状态',
              children: detail.data.enabled ? '启用' : '停用',
            },
            {
              key: 'created_at',
              label: '创建时间',
              children: new Date(detail.data.created_at).toLocaleString(),
            },
            {
              key: 'updated_at',
              label: '更新时间',
              children: new Date(detail.data.updated_at).toLocaleString(),
            },
          ]}
        />
      ) : (
        <Skeleton active />
      )}
    </Drawer>
  );
}

export default function CommunitiesPage() {
  const { path } = useAdminApp();
  const api = usePropertyWorkspaceApi();
  const state = useListState();
  const { status, hasPermission } = usePropertySession();
  const [detailId, setDetailId] = useState<string | null>(null);
  const filters = {
    page: state.page,
    page_size: state.pageSize,
    name: state.params.get('name') || undefined,
    code: state.params.get('code') || undefined,
    enabled: parseEnabled(state.params.get('enabled')),
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
      title: '操作',
      valueType: 'option',
      render: (_, row) => (
        <>
          <Button type="link" onClick={() => setDetailId(row.id)}>
            查看详情
          </Button>
          {hasPermission('property.house.read') && (
            <Link to={path(`/property/communities/${row.id}/houses`)}>
              房屋管理
            </Link>
          )}
        </>
      ),
    },
  ];
  return (
    <PageContainer title="小区查询">
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
      <ProTable<Community>
        headerTitle="本公司小区"
        rowKey="id"
        columns={columns}
        search={false}
        dataSource={query.data?.items ?? []}
        loading={query.isFetching}
        pagination={{ ...state.pagination, total: query.data?.total ?? 0 }}
        scroll={{ x: 800 }}
        options={{ reload: () => void query.refetch() }}
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
      />
      {detailId && (
        <CommunityDetails id={detailId} close={() => setDetailId(null)} />
      )}
    </PageContainer>
  );
}
