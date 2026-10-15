import { useState } from 'react';
import { Link, useNavigate, useParams } from '@umijs/max';
import {
  PageContainer,
  ProTable,
  type ProColumns,
} from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
} from 'antd';
import { useAdminApp } from '../../../shared/admin-app-context';
import { useListState } from '../../../shared/hooks/use-list-state';
import { parseEnabled } from '../../../shared/filters';
import {
  ListEmpty,
  OperationError,
  ReadError,
} from '../../../components/AdminFeedback';
import { usePropertySession, usePropertyWorkspaceApi } from '../hooks';
import { useHousingApi, useHousingOperation } from './hooks';
import type { House, SpaceNode } from './api';
import { CommunityPicker } from './CommunityPicker';
import { SpaceBranch } from './SpaceTree';
import { HousingStatus } from './HousingStatus';
import { HouseEditor, SpaceEditor } from './HousingEditors';
import { StatusAction } from './StatusAction';

interface SearchValues {
  room_no?: string;
  external_code?: string;
  floor_no?: number;
  enabled?: string;
  sort?: string;
}
type Editor =
  { kind: 'space'; node?: SpaceNode } | { kind: 'house'; house?: House };

export default function HousesPage() {
  const { community_id: communityId = '' } = useParams<{
    community_id: string;
  }>();
  const { path } = useAdminApp();
  const navigate = useNavigate();
  const workspace = usePropertyWorkspaceApi();
  const { status, hasPermission } = usePropertySession();
  const community = useQuery({
    queryKey: ['communities', 'detail', communityId],
    queryFn: () => workspace.community(communityId),
    enabled:
      !!communityId &&
      status === 'authenticated' &&
      hasPermission('property.community.read'),
  });
  return (
    <PageContainer
      title={community.data ? `${community.data.name} · 房屋管理` : '房屋管理'}
      breadcrumb={{ items: [{ title: '房屋管理' }] }}
      content={
        <CommunityPicker
          value={communityId}
          community={community.data}
          onChange={(nextId) => {
            if (nextId !== communityId)
              navigate(path(`/property/communities/${nextId}/houses`));
          }}
          onAutoSelect={(nextId) =>
            navigate(path(`/property/communities/${nextId}/houses`), {
              replace: true,
            })
          }
        />
      }
    >
      {community.isError && (
        <ReadError
          error={community.error}
          retry={() => void community.refetch()}
        />
      )}
      {communityId ? (
        <CommunityHouses
          key={communityId}
          communityId={communityId}
          communityName={community.data?.name}
          communityEnabled={community.data?.enabled}
        />
      ) : (
        <Card>
          <Empty
            description={
              hasPermission('property.community.read')
                ? '请先选择小区，查看和维护房屋资料'
                : '暂无可选小区，请联系管理员开通小区查询权限'
            }
          />
        </Card>
      )}
    </PageContainer>
  );
}

function CommunityHouses({
  communityId,
  communityName,
  communityEnabled,
}: {
  communityId: string;
  communityName?: string;
  communityEnabled?: boolean;
}) {
  const { path } = useAdminApp();
  const state = useListState();
  const api = useHousingApi();
  const { status, hasPermission } = usePropertySession();
  const operation = useHousingOperation();
  const [editor, setEditor] = useState<Editor | null>(null);
  const selectedId = state.params.get('space_node_id') || undefined;
  const canReadSpaces = hasPermission('property.space.read');
  const selected = useQuery({
    queryKey: ['spaces', 'detail', communityId, selectedId],
    queryFn: () => api.node(communityId, selectedId!),
    enabled: !!selectedId && status === 'authenticated' && canReadSpaces,
  });
  const floor = state.params.get('floor_no');
  const parsedFloor =
    floor !== null && /^-?\d+$/.test(floor) ? Number(floor) : undefined;
  const filters = {
    page: state.page,
    page_size: state.pageSize,
    space_node_id: selectedId,
    room_no: state.params.get('room_no') || undefined,
    external_code: state.params.get('external_code') || undefined,
    floor_no:
      parsedFloor !== undefined && parsedFloor >= -32768 && parsedFloor <= 32767
        ? parsedFloor
        : undefined,
    enabled: parseEnabled(state.params.get('enabled')),
    sort:
      state.params.get('sort') === 'created_at' ? 'created_at' : '-created_at',
  };
  const query = useQuery({
    queryKey: ['houses', 'list', communityId, filters],
    queryFn: () => api.houses(communityId, filters),
    enabled: status === 'authenticated' && hasPermission('property.house.read'),
  });
  const node = selected.data;
  const creatingAllowed =
    communityEnabled !== false &&
    (!selectedId || node?.effective_enabled === true);
  const columns: ProColumns<House>[] = [
    { title: '完整位置', dataIndex: 'display_address' },
    { title: '房号', dataIndex: 'room_no' },
    {
      title: '楼层',
      dataIndex: 'floor_no',
      render: (_, row) => row.floor_no ?? '—',
    },
    {
      title: '外部编号',
      dataIndex: 'external_code',
      render: (_, row) => row.external_code ?? '—',
    },
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
    { title: '创建时间', dataIndex: 'created_at', valueType: 'dateTime' },
    {
      title: '操作',
      valueType: 'option',
      render: (_, row) => (
        <Space>
          <Link
            to={path(`/property/communities/${communityId}/houses/${row.id}`)}
          >
            房屋详情
          </Link>
          {hasPermission('property.house.update') && (
            <>
              <Button
                type="link"
                onClick={() => setEditor({ kind: 'house', house: row })}
              >
                编辑
              </Button>
              <StatusAction
                record={row}
                label={`房屋 ${row.room_no}`}
                impact="房屋及业主登记将不可用，保留全部资料与各自启停状态。"
                operation={operation}
                update={(enabled) =>
                  api.updateHouse(communityId, row.id, { enabled })
                }
              />
            </>
          )}
        </Space>
      ),
    },
  ];
  const restore = node
    ? [...node.ancestors.map((part) => part.id), node.id]
    : [];
  return (
    <>
      <OperationError error={operation.error} />
      {communityEnabled === false && (
        <Alert
          type="info"
          showIcon
          title="小区已停用，可维护已有资料；启用小区后才能新增。"
          style={{ marginBottom: 16 }}
        />
      )}
      <Row gutter={[16, 16]}>
        {canReadSpaces && (
          <Col xs={24} lg={{ flex: '0 0 280px' }}>
            <Card title="空间定位">
              <Button
                type={!selectedId ? 'primary' : 'default'}
                onClick={() =>
                  state.update({ space_node_id: undefined, page: 1 })
                }
              >
                {communityName ?? '全部房屋'}
              </Button>
              <div role="tree" aria-label="小区空间" style={{ marginTop: 12 }}>
                <SpaceBranch
                  communityId={communityId}
                  selectedId={selectedId}
                  restorePath={restore}
                  onSelect={(item) =>
                    state.update({ space_node_id: item.id, page: 1 })
                  }
                />
              </div>
            </Card>
          </Col>
        )}
        <Col xs={24} lg={{ flex: '1 1 0%' }} style={{ minWidth: 0 }}>
          {selected.isError && (
            <ReadError
              error={selected.error}
              retry={() => void selected.refetch()}
            />
          )}
          <Card
            title={
              node
                ? [...node.ancestors.map((part) => part.name), node.name].join(
                    '／',
                  )
                : '小区全部房屋'
            }
            style={{ marginBottom: 16 }}
          >
            <Space wrap>
              {node && (
                <>
                  <HousingStatus enabled={node.enabled} />
                  <HousingStatus
                    enabled={node.enabled}
                    effective={node.effective_enabled}
                  />
                </>
              )}
              {canReadSpaces &&
                hasPermission('property.space.create') &&
                (!selectedId || (node && node.node_type !== 'unit')) && (
                  <Button
                    disabled={!creatingAllowed}
                    onClick={() => setEditor({ kind: 'space' })}
                  >
                    新增空间
                  </Button>
                )}
              {node && hasPermission('property.space.update') && (
                <>
                  <Button onClick={() => setEditor({ kind: 'space', node })}>
                    编辑空间
                  </Button>
                  <StatusAction
                    record={node}
                    label={`空间 ${node.name}`}
                    impact="所属空间、房屋和业主登记将不可用；各记录自身状态保留。"
                    operation={operation}
                    update={(enabled) =>
                      api.updateNode(communityId, node.id, { enabled })
                    }
                  />
                </>
              )}
              {canReadSpaces && hasPermission('property.house.create') && (
                <Button
                  type="primary"
                  disabled={!creatingAllowed}
                  onClick={() => setEditor({ kind: 'house' })}
                >
                  新增房屋
                </Button>
              )}
            </Space>
          </Card>
          <Card style={{ marginBottom: 16 }}>
            <Form<SearchValues>
              key={[
                filters.room_no,
                filters.external_code,
                filters.floor_no,
                filters.enabled,
                filters.sort,
              ].join('|')}
              layout="inline"
              initialValues={{
                ...filters,
                enabled:
                  filters.enabled === undefined
                    ? undefined
                    : String(filters.enabled),
              }}
              onFinish={(values) => state.update({ ...values, page: 1 })}
            >
              <Form.Item name="room_no" label="房号">
                <Input allowClear maxLength={32} style={{ width: 120 }} />
              </Form.Item>
              <Form.Item name="external_code" label="外部编号">
                <Input allowClear maxLength={64} style={{ width: 120 }} />
              </Form.Item>
              <Form.Item name="floor_no" label="楼层">
                <InputNumber min={-32768} max={32767} precision={0} />
              </Form.Item>
              <Form.Item name="enabled" label="自身状态">
                <Select
                  allowClear
                  style={{ width: 100 }}
                  options={[
                    { value: 'true', label: '启用' },
                    { value: 'false', label: '停用' },
                  ]}
                />
              </Form.Item>
              <Form.Item name="sort" label="时间排序">
                <Select
                  style={{ width: 120 }}
                  options={[
                    { value: '-created_at', label: '最新在前' },
                    { value: 'created_at', label: '最早在前' },
                  ]}
                />
              </Form.Item>
              <Form.Item>
                <Space>
                  <Button htmlType="submit" type="primary">
                    查询
                  </Button>
                  <Button
                    onClick={() =>
                      state.update({
                        room_no: undefined,
                        external_code: undefined,
                        floor_no: undefined,
                        enabled: undefined,
                        sort: undefined,
                        page: 1,
                      })
                    }
                  >
                    重置
                  </Button>
                </Space>
              </Form.Item>
            </Form>
          </Card>
          {query.isError && (
            <ReadError error={query.error} retry={() => void query.refetch()} />
          )}
          <ProTable<House>
            headerTitle="房屋档案"
            rowKey="id"
            search={false}
            columns={columns}
            dataSource={query.data?.items ?? []}
            loading={query.isFetching}
            pagination={{ ...state.pagination, total: query.data?.total ?? 0 }}
            scroll={{ x: 1300 }}
            options={{ reload: () => void query.refetch() }}
            locale={{
              emptyText: (
                <ListEmpty
                  filtered={
                    !!selectedId ||
                    !!filters.room_no ||
                    !!filters.external_code ||
                    filters.floor_no !== undefined ||
                    filters.enabled !== undefined
                  }
                />
              ),
            }}
          />
        </Col>
      </Row>
      {editor?.kind === 'space' && (
        <SpaceEditor
          communityId={communityId}
          node={editor.node}
          parent={node}
          done={() => setEditor(null)}
        />
      )}
      {editor?.kind === 'house' && (
        <HouseEditor
          communityId={communityId}
          house={editor.house}
          selected={node}
          done={() => setEditor(null)}
        />
      )}
    </>
  );
}
