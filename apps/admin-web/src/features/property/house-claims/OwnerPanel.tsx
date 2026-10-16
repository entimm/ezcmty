import { ProTable, type ProColumns } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Card } from 'antd';
import { ListEmpty, ReadError } from '../../../components/AdminFeedback';
import { useListState } from '../../../shared/hooks/use-list-state';
import { usePropertySession } from '../hooks';
import { useHousingApi } from '../housing/hooks';
import type { HouseOwner } from '../housing/api';
import type { Claim } from './api';

export function OwnerPanel({ claim }: { claim: Claim }) {
  const { status, hasPermission } = usePropertySession();
  const permitted =
    status === 'authenticated' && hasPermission('property.house_owner.read');
  const api = useHousingApi();
  const state = useListState('owner_');
  const query = useQuery({
    queryKey: [
      'house-owners',
      claim.community_id,
      claim.house_id,
      state.page,
      state.pageSize,
    ],
    queryFn: () =>
      api.owners(claim.community_id, claim.house_id, {
        page: state.page,
        page_size: state.pageSize,
        sort: '-created_at',
      }),
    enabled: permitted,
  });
  const columns: ProColumns<HouseOwner>[] = [
    { title: '姓名', dataIndex: 'name' },
    { title: '手机号', dataIndex: 'phone' },
    { title: '档案状态', render: (_, row) => (row.enabled ? '启用' : '停用') },
    {
      title: '申请时匹配记录',
      render: (_, row) => (row.id === claim.matched_owner_id ? '是' : '—'),
    },
  ];
  return (
    <Card title="现有业主档案">
      {!permitted ? (
        <p>没有业主资料读取权限。</p>
      ) : (
        <>
          <p>以下为当前档案，可能与申请时不同；独立审批通过不会修改档案。</p>
          {query.isError && (
            <ReadError error={query.error} retry={() => void query.refetch()} />
          )}
          <ProTable<HouseOwner>
            rowKey="id"
            search={false}
            columns={columns}
            dataSource={query.data?.items ?? []}
            loading={query.isFetching}
            pagination={{ ...state.pagination, total: query.data?.total ?? 0 }}
            options={{ reload: () => void query.refetch() }}
            locale={{ emptyText: <ListEmpty filtered={false} /> }}
          />
        </>
      )}
    </Card>
  );
}
