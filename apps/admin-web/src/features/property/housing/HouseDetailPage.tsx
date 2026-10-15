import { useState } from 'react';
import { Link, useParams } from '@umijs/max';
import {
  PageContainer,
  ProTable,
  type ProColumns,
} from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Alert, Button, Card, Descriptions, Space, Spin } from 'antd';
import { useAdminApp } from '../../../shared/admin-app-context';
import { useListState } from '../../../shared/hooks/use-list-state';
import {
  ListEmpty,
  OperationError,
  ReadError,
} from '../../../components/AdminFeedback';
import { usePropertySession } from '../hooks';
import { useHousingApi, useHousingOperation } from './hooks';
import type { House, HouseOwner } from './api';
import { HousingStatus } from './HousingStatus';
import { HouseEditor, OwnerEditor } from './HousingEditors';
import { StatusAction } from './StatusAction';

function Owners({ communityId, house }: { communityId: string; house: House }) {
  const api = useHousingApi();
  const { status, hasPermission } = usePropertySession();
  const state = useListState('owner_');
  const [editor, setEditor] = useState<{ owner?: HouseOwner } | null>(null);
  const operation = useHousingOperation();
  const canRead = hasPermission('property.house_owner.read');
  const filters = {
    page: state.page,
    page_size: state.pageSize,
    sort: '-created_at',
  };
  const query = useQuery({
    queryKey: ['house-owners', 'list', communityId, house.id, filters],
    queryFn: () => api.owners(communityId, house.id, filters),
    enabled: status === 'authenticated' && canRead,
  });
  const columns: ProColumns<HouseOwner>[] = [
    { title: '业主姓名', dataIndex: 'name' },
    { title: '手机号', dataIndex: 'phone' },
    {
      title: '自身状态',
      render: (_, row) => <HousingStatus enabled={row.enabled} />,
    },
    {
      title: '实际可用',
      render: (_, row) => (
        <HousingStatus
          enabled={row.enabled}
          effective={row.effective_enabled}
        />
      ),
    },
    { title: '登记时间', dataIndex: 'created_at', valueType: 'dateTime' },
    {
      title: '操作',
      valueType: 'option',
      render: (_, row) =>
        hasPermission('property.house_owner.update') ? (
          <Space>
            <Button type="link" onClick={() => setEditor({ owner: row })}>
              编辑业主
            </Button>
            <StatusAction
              record={row}
              label="此业主登记"
              impact="此登记将不可用，姓名和手机号保留。更换业主时请另行新增登记。"
              operation={operation}
              update={(enabled) =>
                api.updateOwner(communityId, house.id, row.id, { enabled })
              }
            />
          </Space>
        ) : null,
    },
  ];
  return (
    <Card
      title="业主登记"
      extra={
        hasPermission('property.house_owner.create') && (
          <Button
            type="primary"
            disabled={!house.effective_enabled}
            onClick={() => setEditor({})}
          >
            新增业主
          </Button>
        )
      }
    >
      <OperationError error={operation.error} />
      {canRead ? (
        <>
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
            scroll={{ x: 850 }}
            options={{ reload: () => void query.refetch() }}
            locale={{ emptyText: <ListEmpty filtered={false} /> }}
          />
        </>
      ) : (
        <p>没有业主资料读取权限。</p>
      )}
      {editor && (
        <OwnerEditor
          communityId={communityId}
          houseId={house.id}
          owner={editor.owner}
          done={() => setEditor(null)}
        />
      )}
    </Card>
  );
}
export default function HouseDetailPage() {
  const { community_id: communityId = '', house_id: houseId = '' } = useParams<{
    community_id: string;
    house_id: string;
  }>();
  const { path } = useAdminApp();
  const api = useHousingApi();
  const { status, hasPermission } = usePropertySession();
  const [editing, setEditing] = useState(false);
  const operation = useHousingOperation();
  const query = useQuery({
    queryKey: ['houses', 'detail', communityId, houseId],
    queryFn: () => api.house(communityId, houseId),
    enabled: status === 'authenticated' && hasPermission('property.house.read'),
  });
  const house = query.data;
  const back = path(`/property/communities/${communityId}/houses`);
  return (
    <PageContainer
      title={house ? `房屋 ${house.room_no}` : '房屋详情'}
      breadcrumb={{
        items: [
          { title: <Link to={back}>房屋管理</Link> },
          { title: '房屋详情' },
        ],
      }}
      extra={
        <Space>
          {house && hasPermission('property.house.update') && (
            <>
              <Button onClick={() => setEditing(true)}>编辑房屋</Button>
              <StatusAction
                record={house}
                label={`房屋 ${house.room_no}`}
                impact="房屋及业主登记将不可用，全部资料和各自状态保留。"
                operation={operation}
                update={(enabled) =>
                  api.updateHouse(communityId, house.id, { enabled })
                }
              />
            </>
          )}
          <Link to={back}>返回房屋列表</Link>
        </Space>
      }
    >
      <OperationError error={operation.error} />
      {query.isError ? (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      ) : query.isPending ? (
        <Spin />
      ) : (
        house && (
          <Space orientation="vertical" size="large" style={{ width: '100%' }}>
            {!house.effective_enabled && (
              <Alert
                type="info"
                showIcon
                title="房屋当前不可用，可修正已有资料；新增业主需要房屋及上级全部启用。"
              />
            )}
            <Card title="房屋资料">
              <Descriptions
                column={{ xs: 1, sm: 2 }}
                items={[
                  {
                    key: 'address',
                    label: '完整位置',
                    children: house.display_address,
                    span: 2,
                  },
                  { key: 'room', label: '房号', children: house.room_no },
                  {
                    key: 'floor',
                    label: '楼层',
                    children: house.floor_no ?? '—',
                  },
                  {
                    key: 'external',
                    label: '外部编号',
                    children: house.external_code ?? '—',
                  },
                  {
                    key: 'enabled',
                    label: '自身状态',
                    children: <HousingStatus enabled={house.enabled} />,
                  },
                  {
                    key: 'effective',
                    label: '实际可用',
                    children: (
                      <HousingStatus
                        enabled={house.enabled}
                        effective={house.effective_enabled}
                      />
                    ),
                  },
                  {
                    key: 'created',
                    label: '创建时间',
                    children: new Date(house.created_at).toLocaleString(),
                  },
                  {
                    key: 'updated',
                    label: '更新时间',
                    children: new Date(house.updated_at).toLocaleString(),
                  },
                ]}
              />
            </Card>
            <Owners communityId={communityId} house={house} />
          </Space>
        )
      )}
      {house && editing && (
        <HouseEditor
          communityId={communityId}
          house={house}
          done={() => setEditing(false)}
        />
      )}
    </PageContainer>
  );
}
