import { useMemo, useState } from 'react';
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ApartmentOutlined,
  DownloadOutlined,
  EditOutlined,
  EllipsisOutlined,
  PlusOutlined,
  SearchOutlined,
  UserOutlined,
} from '@ant-design/icons';
import {
  Alert,
  App,
  Avatar,
  Button,
  Col,
  DatePicker,
  Divider,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  Radio,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Tree,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { DataNode } from 'antd/es/tree';
import dayjs, { type Dayjs } from 'dayjs';
import { useAdmin } from '../../shared/context';
import { PageHeader, Panel, DetailGrid } from '../../shared/ui';
import {
  createPropertyApi,
  type FeeBasis,
  type House,
  type Owner,
  type SpaceNode,
  type SpaceType,
  type Usage,
} from './api';
import { PropertyEditor } from './Editor';
import {
  basisText,
  cents,
  HousingStatus,
  Metric,
  Metrics,
  QueryError,
  SelectCommunity,
  time,
  toCents,
  usageLabels,
} from './presentation';
import { BillList, BillModal } from './Billing';

const spaceLabels = { phase: '分区', building: '楼栋', unit: '单元' };
const phoneRule = {
  pattern: /^(?:(?:\+86|0086))?1[3-9][0-9]{9}$/,
  message: '请输入有效大陆手机号，可带 +86 或 0086 前缀',
};
type Editor = {
  kind:
    | 'house'
    | 'space'
    | 'owner'
    | 'house-status'
    | 'space-status'
    | 'owner-status'
    | 'basis'
    | 'basis-view';
  house?: House;
  owner?: Owner;
  node?: SpaceNode;
  basis?: FeeBasis;
};

async function loadSpaces(
  api: ReturnType<typeof createPropertyApi>,
  c: string,
) {
  const all: SpaceNode[] = [];
  async function level(parentId?: string) {
    const children: SpaceNode[] = [];
    let page = 1;
    while (true) {
      const result = await api.nodes(c, {
        parent_id: parentId,
        page,
        page_size: 100,
      });
      children.push(...result.items);
      if (children.length >= result.total || result.items.length === 0) break;
      page += 1;
    }
    all.push(...children);
    await Promise.all(
      children.filter((n) => n.has_children).map((n) => level(n.id)),
    );
  }
  await level();
  return all;
}

export function HousingPage({ detail = false }: { detail?: boolean }) {
  const { request, can, communityId, community, params, go } = useAdmin();
  const api = useMemo(() => createPropertyApi(request), [request]);
  const cache = useQueryClient();
  const [editor, setEditor] = useState<Editor>();
  const [createBill, setCreateBill] = useState(false);
  const [searchText, setSearchText] = useState(
    params.room_no || params.external_code || '',
  );
  const [searchBy, setSearchBy] = useState(
    params.external_code ? 'external_code' : 'room_no',
  );
  const [enabled, setEnabled] = useState<string | undefined>(params.enabled);
  const c = communityId || params.community_id || '';
  const id = params.house_id || params.id || '';
  const listPage = Number(params.page) || 1;
  const pageSize = Number(params.page_size) || 20;
  const selectedSpaceId = params.space_node_id || 'all';
  const spaces = useQuery({
    queryKey: ['property', 'spaces', c],
    queryFn: () => loadSpaces(api, c),
    enabled: !!c && can('property.space.read'),
  });
  const list = useQuery({
    queryKey: ['property', 'houses', c, params],
    queryFn: () =>
      api.houses(c, {
        page: listPage,
        page_size: pageSize,
        space_node_id: params.space_node_id,
        room_no: params.room_no,
        external_code: params.external_code,
        enabled:
          params.enabled === undefined ? undefined : params.enabled === 'true',
        sort: '-created_at',
      }),
    enabled: !!c && !detail && can('property.house.read'),
  });
  const houseQuery = useQuery({
    queryKey: ['property', 'house', c, id],
    queryFn: () => api.house(c, id),
    enabled: !!c && !!id && detail && can('property.house.read'),
  });
  const totals = useQuery({
    queryKey: ['property', 'house-counts', c],
    queryFn: async () => {
      const [total, active] = await Promise.all([
        api.houses(c, { page: 1, page_size: 1 }),
        api.houses(c, { page: 1, page_size: 1, enabled: true }),
      ]);
      return { total: total.total, active: active.total };
    },
    enabled: !!c && !detail && can('property.house.read'),
  });
  const rows = list.data?.items ?? [];
  const metadata = useQueries({
    queries: rows.map((house) => ({
      queryKey: [
        'property',
        'house-metadata',
        c,
        house.id,
        can('property.house_owner.read'),
        can('property.fee_basis.read'),
      ],
      queryFn: async () => {
        const [owners, bases] = await Promise.all([
          can('property.house_owner.read')
            ? api.owners(c, house.id, { page: 1, page_size: 100 })
            : null,
          can('property.fee_basis.read')
            ? api.bases(c, house.id, { page: 1, page_size: 1 })
            : null,
        ]);
        return { owners, basis: bases?.items[0] };
      },
    })),
  });
  const meta = new Map(rows.map((row, i) => [row.id, metadata[i]]));
  const selectedSpace = spaces.data?.find(
    (node) => node.id === selectedSpaceId,
  );
  const house = houseQuery.data;
  const available = community?.enabled !== false;
  const invalidate = async () => {
    await cache.invalidateQueries({ queryKey: ['property'] });
  };
  const openHouse = (row: House, tab?: string) =>
    go('house-detail', { community_id: c, house_id: row.id, tab });
  const nodeChildren = (parentId: string | null): DataNode[] =>
    (spaces.data ?? [])
      .filter((n) => n.parent_id === parentId)
      .map((n) => ({
        key: n.id,
        title: (
          <span>
            {n.name}
            {!n.effective_enabled && <Tag style={{ marginLeft: 6 }}>停用</Tag>}
          </span>
        ),
        children: nodeChildren(n.id),
      }));
  const columns: ColumnsType<House> = [
    {
      title: '房屋位置',
      key: 'house',
      width: 250,
      render: (_, row) => (
        <div>
          <a onClick={() => openHouse(row)}>{row.display_address}</a>
          <div className="muted" style={{ fontSize: 12, marginTop: 5 }}>
            {row.external_code || '未填写外部编号'}
          </div>
        </div>
      ),
    },
    {
      title: '面积 / 用途',
      width: 145,
      render: (_, row) => {
        const data = meta.get(row.id);
        return data?.isPending ? (
          <Spin size="small" />
        ) : data?.isError ? (
          <Tooltip title="读取失败，打开详情可重试">读取失败</Tooltip>
        ) : (
          <div>
            {data?.data?.basis?.area_sqm
              ? `${data.data.basis.area_sqm} ㎡`
              : '未设置'}
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
              {data?.data?.basis
                ? usageLabels[data.data.basis.house_usage]
                : can('property.fee_basis.read')
                  ? '暂无计费依据'
                  : '无计费读取权限'}
            </div>
          </div>
        );
      },
    },
    {
      title: '业主登记',
      width: 160,
      render: (_, row) => {
        const data = meta.get(row.id);
        if (!can('property.house_owner.read'))
          return <span className="muted">无读取权限</span>;
        if (data?.isPending) return <Spin size="small" />;
        if (data?.isError) return <span className="muted">读取失败</span>;
        const owners =
          data?.data?.owners?.items.filter((owner) => owner.enabled) ?? [];
        return owners.length ? (
          <Space>
            <Avatar
              size={26}
              icon={<UserOutlined />}
              style={{ background: '#eef2ff', color: '#5067b5' }}
            />
            <span>
              {owners[0].name}
              {owners.length > 1 ? ` 等 ${owners.length} 人` : ''}
            </span>
          </Space>
        ) : (
          <span style={{ color: '#a37721' }}>待补充</span>
        );
      },
    },
    {
      title: '状态',
      width: 100,
      render: (_, row) => <HousingStatus record={row} />,
    },
    {
      title: '操作',
      width: 205,
      fixed: 'right',
      render: (_, row) => (
        <Space size={2}>
          <Button type="link" size="small" onClick={() => openHouse(row)}>
            详情
          </Button>
          {can('property.house_owner.create') && (
            <Tooltip
              title={
                !row.effective_enabled
                  ? '房屋或上级已停用，暂不能新增业主登记'
                  : '为此房屋快捷登记业主'
              }
            >
              <Button
                type="link"
                size="small"
                disabled={!row.effective_enabled}
                onClick={() => setEditor({ kind: 'owner', house: row })}
              >
                登记业主
              </Button>
            </Tooltip>
          )}
          {can('property.house.update') && (
            <Dropdown
              menu={{
                items: [
                  {
                    key: 'edit',
                    label: '编辑房屋资料',
                    icon: <EditOutlined />,
                    onClick: () => setEditor({ kind: 'house', house: row }),
                  },
                  {
                    key: 'state',
                    label: row.enabled ? '停用房屋' : '启用房屋',
                    danger: row.enabled,
                    onClick: () =>
                      setEditor({ kind: 'house-status', house: row }),
                  },
                ],
              }}
            >
              <Button type="text" size="small" icon={<EllipsisOutlined />} />
            </Dropdown>
          )}
        </Space>
      ),
    },
  ];
  if (!c)
    return (
      <>
        <PageHeader
          title="房屋档案"
          description="以房屋为核心，统一维护空间、业主登记与计费资料。"
        />
        <SelectCommunity />
      </>
    );
  return (
    <div className="property-pages">
      {detail ? (
        <>
          <PageHeader
            title={house?.display_address || '房屋详情'}
            description={`${community?.name ?? ''} · 房屋档案 / 业主与计费资料`}
            back={() => go('houses')}
            extra={
              house && (
                <>
                  <HousingStatus record={house} />
                  {can('property.house.update') && (
                    <Button
                      icon={<EditOutlined />}
                      onClick={() => setEditor({ kind: 'house', house })}
                    >
                      编辑房屋
                    </Button>
                  )}
                </>
              )
            }
          />
          <QueryError error={houseQuery.error} retry={houseQuery.refetch} />
          {houseQuery.isPending && <Spin />}
          {house && (
            <>
              {!house.effective_enabled && (
                <Alert
                  showIcon
                  type="warning"
                  title="房屋当前不可用"
                  description="可查看与修正资料；新增业主、计费依据、账单和收款暂不可用。"
                  style={{ marginBottom: 20 }}
                />
              )}
              <Panel title="基础资料">
                <DetailGrid
                  items={[
                    ['房屋位置', house.display_address],
                    ['房号', house.room_no],
                    [
                      '所在楼层',
                      house.floor_no === null
                        ? '未填写'
                        : `${house.floor_no} 层`,
                    ],
                    ['外部编号', house.external_code || '未填写'],
                    ['建档日期', time(house.created_at)],
                    ['实际状态', <HousingStatus key="state" record={house} />],
                  ]}
                />
              </Panel>
              <Tabs
                activeKey={
                  params.tab ||
                  (can('property.house_owner.read')
                    ? 'owners'
                    : can('property.fee_basis.read')
                      ? 'basis'
                      : 'bills')
                }
                onChange={(tab) =>
                  go('house-detail', { community_id: c, house_id: id, tab })
                }
                style={{ marginTop: 20 }}
                items={[
                  ...(can('property.house_owner.read')
                    ? [
                        {
                          key: 'owners',
                          label: '业主登记',
                          children: (
                            <OwnerPanel
                              house={house}
                              open={(value) => setEditor(value)}
                            />
                          ),
                        },
                      ]
                    : []),
                  ...(can('property.fee_basis.read')
                    ? [
                        {
                          key: 'basis',
                          label: '计费依据',
                          children: (
                            <BasisPanel
                              house={house}
                              open={(value) => setEditor(value)}
                            />
                          ),
                        },
                      ]
                    : []),
                  ...(can('property.bill.read')
                    ? [
                        {
                          key: 'bills',
                          label: '房屋账单',
                          children: (
                            <Panel
                              title="当前房屋账单"
                              extra={
                                can('property.bill.create') && (
                                  <Button
                                    type="primary"
                                    icon={<PlusOutlined />}
                                    disabled={!house.effective_enabled}
                                    onClick={() => setCreateBill(true)}
                                  >
                                    新增账单
                                  </Button>
                                )
                              }
                            >
                              <BillList houseId={house.id} />
                            </Panel>
                          ),
                        },
                      ]
                    : []),
                ]}
              />
            </>
          )}
        </>
      ) : (
        <>
          <PageHeader
            title="房屋档案"
            description="以房屋为核心，统一维护空间、业主登记与计费资料。"
            extra={
              <>
                {can('property.import.create') && (
                  <Button
                    icon={<DownloadOutlined />}
                    onClick={() => go('import-new', { import_type: 'houses' })}
                  >
                    导入房屋 / 业主
                  </Button>
                )}
                {can('property.house.create') && (
                  <Button
                    type="primary"
                    icon={<PlusOutlined />}
                    disabled={!available}
                    onClick={() => setEditor({ kind: 'house' })}
                  >
                    新增房屋
                  </Button>
                )}
              </>
            }
          />
          <Metrics>
            <Metric
              label="当前房屋"
              value={totals.data?.total ?? '—'}
              sub={`${community?.name ?? '当前小区'} · 全部房屋`}
            />
            <Metric
              label="自身启用"
              value={totals.data?.active ?? '—'}
              sub="实际可用状态同时受上级影响"
              color="#237c63"
            />
            <Metric
              label="本页业主待补充"
              value={
                !can('property.house_owner.read') ||
                metadata.some((m) => !m.isSuccess)
                  ? '—'
                  : metadata.filter(
                      (m) => !m.data?.owners?.items.some((o) => o.enabled),
                    ).length
              }
              sub="补充档案，提高认领审核效率"
              color="#c28728"
            />
            <Metric
              label="已停用"
              value={totals.data ? totals.data.total - totals.data.active : '—'}
              sub="保留历史资料与关联记录"
            />
          </Metrics>
          {!available && (
            <Alert
              showIcon
              type="warning"
              title="当前小区已停用"
              description="可查看与修正历史资料。新增房屋、业主、计费依据及账单暂不可用。"
              style={{ marginBottom: 20 }}
            />
          )}
          <QueryError
            error={list.error || spaces.error || totals.error}
            retry={invalidate}
          />
          <div
            className="housing-layout"
            style={{
              display: 'grid',
              gridTemplateColumns: '226px minmax(0, 1fr)',
              gap: 18,
              alignItems: 'start',
            }}
          >
            <Panel
              title="空间定位"
              extra={<ApartmentOutlined style={{ color: '#7b89a2' }} />}
            >
              <Spin spinning={spaces.isPending && can('property.space.read')}>
                <Tree
                  blockNode
                  defaultExpandedKeys={['all']}
                  selectedKeys={[selectedSpaceId]}
                  treeData={[
                    {
                      title: <strong>{community?.name ?? '全部房屋'}</strong>,
                      key: 'all',
                      children: nodeChildren(null),
                    },
                  ]}
                  onSelect={(keys) =>
                    go('houses', {
                      ...params,
                      space_node_id:
                        keys[0] && keys[0] !== 'all'
                          ? String(keys[0])
                          : undefined,
                      page: '1',
                    })
                  }
                  style={{ background: 'transparent', fontSize: 13 }}
                />
              </Spin>
              {can('property.space.create') && (
                <>
                  <Divider style={{ margin: '20px 0 12px' }} />
                  <Button
                    type="text"
                    icon={<PlusOutlined />}
                    block
                    disabled={
                      !available ||
                      (!!selectedSpace && !selectedSpace.effective_enabled) ||
                      selectedSpace?.node_type === 'unit'
                    }
                    onClick={() => setEditor({ kind: 'space' })}
                  >
                    新增空间
                  </Button>
                </>
              )}
            </Panel>
            <Panel
              title={selectedSpace?.name ?? '全部房屋'}
              extra={
                selectedSpace &&
                can('property.space.update') && (
                  <Space>
                    <Button
                      type="link"
                      size="small"
                      onClick={() =>
                        setEditor({ kind: 'space', node: selectedSpace })
                      }
                    >
                      编辑空间
                    </Button>
                    <Button
                      type="link"
                      size="small"
                      danger={selectedSpace.enabled}
                      onClick={() =>
                        setEditor({ kind: 'space-status', node: selectedSpace })
                      }
                    >
                      {selectedSpace.enabled ? '停用空间' : '启用空间'}
                    </Button>
                  </Space>
                )
              }
            >
              <div
                className="filter-bar"
                style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 12,
                  alignItems: 'center',
                }}
              >
                <Space.Compact>
                  <Select
                    value={searchBy}
                    onChange={setSearchBy}
                    style={{ width: 105 }}
                    options={[
                      { label: '按房号', value: 'room_no' },
                      { label: '外部编号', value: 'external_code' },
                    ]}
                  />
                  <Input
                    allowClear
                    prefix={<SearchOutlined style={{ color: '#8590a4' }} />}
                    placeholder="输入完整内容查询"
                    value={searchText}
                    onChange={(e) => setSearchText(e.target.value)}
                    onPressEnter={() =>
                      go('houses', {
                        ...params,
                        room_no: undefined,
                        external_code: undefined,
                        [searchBy]: searchText.trim(),
                        enabled,
                        page: '1',
                      })
                    }
                    style={{ width: 210 }}
                  />
                </Space.Compact>
                <Select
                  allowClear
                  placeholder="全部状态"
                  value={enabled}
                  onChange={setEnabled}
                  style={{ width: 130 }}
                  options={[
                    { value: 'true', label: '已启用' },
                    { value: 'false', label: '已停用' },
                  ]}
                />
                <Space style={{ marginLeft: 'auto' }}>
                  <Button
                    type="primary"
                    onClick={() =>
                      go('houses', {
                        ...params,
                        room_no: undefined,
                        external_code: undefined,
                        [searchBy]: searchText.trim(),
                        enabled,
                        page: '1',
                      })
                    }
                  >
                    查询
                  </Button>
                  <Button
                    onClick={() => {
                      setSearchText('');
                      setEnabled(undefined);
                      go('houses', {
                        community_id: c,
                        space_node_id: params.space_node_id,
                      });
                    }}
                  >
                    重置
                  </Button>
                </Space>
              </div>
              <Table<House>
                size="middle"
                rowKey="id"
                columns={columns}
                dataSource={rows}
                loading={list.isPending}
                pagination={{
                  current: listPage,
                  pageSize,
                  total: list.data?.total,
                  showSizeChanger: true,
                  showTotal: (total) => `共 ${total} 条`,
                  onChange: (page, size) =>
                    go('houses', {
                      ...params,
                      page: String(page),
                      page_size: String(size),
                    }),
                }}
                scroll={{ x: 900 }}
                locale={{
                  emptyText: <Empty description="没有符合条件的房屋" />,
                }}
                style={{ marginTop: 20 }}
              />
            </Panel>
          </div>
        </>
      )}
      {editor && (
        <HousingEditor
          key={`${editor.kind}-${editor.house?.id ?? ''}-${editor.owner?.id ?? ''}-${editor.node?.id ?? ''}`}
          editor={editor}
          c={c}
          spaces={spaces.data ?? []}
          selectedSpace={selectedSpace}
          close={() => setEditor(undefined)}
          done={invalidate}
        />
      )}
      {createBill && house && (
        <BillModal house={house} close={() => setCreateBill(false)} />
      )}
    </div>
  );
}

function OwnerPanel({
  house,
  open,
}: {
  house: House;
  open: (editor: Editor) => void;
}) {
  const { request, can } = useAdmin();
  const api = useMemo(() => createPropertyApi(request), [request]);
  const [page, setPage] = useState(1);
  const list = useQuery({
    queryKey: ['property', 'owners', house.community_id, house.id, page],
    queryFn: () =>
      api.owners(house.community_id, house.id, { page, page_size: 20 }),
    enabled: can('property.house_owner.read'),
  });
  return (
    <Panel
      title="业主登记"
      extra={
        can('property.house_owner.create') && (
          <Button
            type="primary"
            size="small"
            icon={<PlusOutlined />}
            disabled={!house.effective_enabled}
            onClick={() => open({ kind: 'owner', house })}
          >
            新增业主
          </Button>
        )
      }
    >
      <Alert
        showIcon
        type="info"
        title="业主登记用于资料核验，与居民房屋使用权限分别管理。"
        style={{ marginBottom: 18 }}
      />
      <QueryError error={list.error} retry={list.refetch} />
      <Table<Owner>
        size="middle"
        rowKey="id"
        dataSource={list.data?.items}
        loading={list.isPending}
        pagination={{
          current: page,
          pageSize: 20,
          total: list.data?.total,
          onChange: setPage,
          showTotal: (total) => `共 ${total} 条`,
        }}
        columns={[
          {
            title: '业主姓名',
            dataIndex: 'name',
            render: (name: string) => (
              <Space>
                <Avatar
                  size={28}
                  icon={<UserOutlined />}
                  style={{ color: '#5269b0', background: '#eef2fb' }}
                />
                <strong>{name}</strong>
              </Space>
            ),
          },
          { title: '联系电话', dataIndex: 'phone' },
          { title: '登记时间', dataIndex: 'created_at', render: time },
          {
            title: '状态',
            render: (_, owner) => <HousingStatus record={owner} />,
          },
          {
            title: '操作',
            render: (_, owner) =>
              can('property.house_owner.update') ? (
                <Space>
                  <Button
                    type="link"
                    size="small"
                    onClick={() => open({ kind: 'owner', house, owner })}
                  >
                    编辑
                  </Button>
                  <Button
                    type="link"
                    size="small"
                    danger={owner.enabled}
                    onClick={() => open({ kind: 'owner-status', house, owner })}
                  >
                    {owner.enabled ? '停用登记' : '启用登记'}
                  </Button>
                </Space>
              ) : (
                '只读'
              ),
          },
        ]}
        locale={{ emptyText: <Empty description="暂未登记业主资料" /> }}
      />
    </Panel>
  );
}

function BasisPanel({
  house,
  open,
}: {
  house: House;
  open: (editor: Editor) => void;
}) {
  const { request, can } = useAdmin();
  const api = useMemo(() => createPropertyApi(request), [request]);
  const [month, setMonth] = useState<Dayjs>(dayjs());
  const [page, setPage] = useState(1);
  const bases = useQuery({
    queryKey: ['property', 'bases', house.community_id, house.id, page],
    queryFn: () =>
      api.bases(house.community_id, house.id, { page, page_size: 20 }),
  });
  const calculation = useQuery({
    queryKey: [
      'property',
      'calculation',
      house.community_id,
      house.id,
      month.format('YYYY-MM'),
    ],
    queryFn: () =>
      api.calculate(house.community_id, house.id, month.format('YYYY-MM')),
    retry: false,
  });
  return (
    <>
      <Panel
        title="当月计费试算"
        extra={
          <DatePicker
            picker="month"
            allowClear={false}
            value={month}
            onChange={(value) => value && setMonth(value)}
          />
        }
      >
        <QueryError error={calculation.error} retry={calculation.refetch} />
        <Spin spinning={calculation.isPending}>
          <DetailGrid
            items={[
              [
                '适用依据',
                calculation.data?.basis
                  ? `v${calculation.data.basis.version_no} · ${calculation.data.basis.effective_from_month} 起生效`
                  : '暂无适用依据',
              ],
              ['计费方式', basisText(calculation.data?.basis)],
              [
                '建筑面积',
                calculation.data?.basis?.area_sqm
                  ? `${calculation.data.basis.area_sqm} ㎡`
                  : '未设置',
              ],
              [
                '本月应收',
                calculation.data?.available
                  ? cents(calculation.data.receivable_cents)
                  : '请先新增计费依据',
              ],
            ]}
          />
        </Spin>
      </Panel>
      <div style={{ height: 18 }} />
      <Panel
        title="计费依据版本"
        extra={
          can('property.fee_basis.create') && (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              disabled={!house.effective_enabled}
              onClick={() => open({ kind: 'basis', house })}
            >
              新增依据版本
            </Button>
          )
        }
      >
        <Alert
          type="info"
          showIcon
          title="版本保存后不可修改。新增版本仅影响后续试算，已经创建的账单继续使用原依据。"
          style={{ marginBottom: 18 }}
        />
        <QueryError error={bases.error} retry={bases.refetch} />
        <Table<FeeBasis>
          rowKey="id"
          size="middle"
          dataSource={bases.data?.items}
          loading={bases.isPending}
          pagination={{
            current: page,
            pageSize: 20,
            total: bases.data?.total,
            onChange: setPage,
          }}
          columns={[
            {
              title: '版本',
              render: (_, basis) => <Tag color="blue">v{basis.version_no}</Tag>,
            },
            { title: '生效月份', dataIndex: 'effective_from_month' },
            { title: '计费标准', render: (_, basis) => basisText(basis) },
            { title: '变更原因', dataIndex: 'change_reason' },
            {
              title: '操作',
              render: (_, basis) => (
                <Space>
                  <Button
                    type="link"
                    size="small"
                    onClick={() => open({ kind: 'basis-view', house, basis })}
                  >
                    详情
                  </Button>
                  {can('property.fee_basis.create') && (
                    <Button
                      type="link"
                      size="small"
                      disabled={!house.effective_enabled}
                      onClick={() => open({ kind: 'basis', house, basis })}
                    >
                      复制为新版本
                    </Button>
                  )}
                </Space>
              ),
            },
          ]}
        />
      </Panel>
    </>
  );
}

function HousingEditor({
  editor,
  c,
  spaces,
  selectedSpace,
  close,
  done,
}: {
  editor: Editor;
  c: string;
  spaces: SpaceNode[];
  selectedSpace?: SpaceNode;
  close: () => void;
  done: () => Promise<void>;
}) {
  const { request, community, can } = useAdmin();
  const { message } = App.useApp();
  const api = useMemo(() => createPropertyApi(request), [request]);
  const [form] = Form.useForm();
  const { kind, house, node, owner, basis } = editor;
  const latest = useQuery({
    queryKey: ['property', 'latest-basis', c, house?.id],
    queryFn: () => api.bases(c, house!.id, { page: 1, page_size: 1 }),
    enabled: kind === 'basis' && !!house && can('property.fee_basis.read'),
  });
  const method = Form.useWatch('method', form) as string | undefined;
  const nodeType = Form.useWatch('node_type', form) as SpaceType | undefined;
  const defaultType =
    selectedSpace?.node_type === 'phase'
      ? 'building'
      : selectedSpace?.node_type === 'building'
        ? 'unit'
        : 'building';
  const basisSource = basis || latest.data?.items[0];
  const initial: Record<string, unknown> =
    kind === 'house'
      ? house
        ? {
            room_no: house.room_no,
            floor_no: house.floor_no,
            external_code: house.external_code,
            space_node_id: house.space_node_id,
          }
        : {
            space_node_id:
              selectedSpace && selectedSpace.node_type !== 'phase'
                ? selectedSpace.id
                : undefined,
            owners: [],
          }
      : kind === 'space'
        ? node
          ? {
              node_type: node.node_type,
              parent_id: node.parent_id ?? 'root',
              name: node.name,
              external_code: node.external_code,
              sort_order: node.sort_order,
            }
          : {
              node_type: defaultType,
              parent_id: selectedSpace?.id || 'root',
              sort_order: 0,
            }
        : kind === 'owner'
          ? { name: owner?.name, phone: owner?.phone }
          : kind === 'basis'
            ? {
                month: dayjs().add(1, 'month'),
                house_usage: basisSource?.house_usage ?? 'residential',
                method:
                  basisSource?.fixed_amount_cents !== null &&
                  basisSource?.fixed_amount_cents !== undefined
                    ? 'fixed'
                    : 'area',
                area: basisSource?.area_sqm
                  ? Number(basisSource.area_sqm)
                  : undefined,
                rate:
                  basisSource?.unit_price_cents !== null &&
                  basisSource?.unit_price_cents !== undefined
                    ? basisSource.unit_price_cents / 100
                    : undefined,
                fixed:
                  basisSource?.fixed_amount_cents !== null &&
                  basisSource?.fixed_amount_cents !== undefined
                    ? basisSource.fixed_amount_cents / 100
                    : undefined,
              }
            : {};
  const title = {
    house: house ? '编辑房屋资料' : '新增房屋',
    space: node ? '编辑空间' : '新增空间',
    owner: owner ? '编辑业主资料' : '新增业主登记',
    'house-status': house?.enabled ? '停用房屋' : '启用房屋',
    'space-status': node?.enabled ? '停用空间' : '启用空间',
    'owner-status': owner?.enabled ? '停用业主登记' : '启用业主登记',
    basis: '新增计费依据版本',
    'basis-view': `计费依据 v${basis?.version_no}`,
  }[kind];
  const submit = async (values: Record<string, unknown>) => {
    if (kind === 'house') {
      if (!can(house ? 'property.house.update' : 'property.house.create'))
        throw new Error('没有操作权限');
      await api.saveHouse(c, house?.id, {
        ...(house
          ? {}
          : {
              space_node_id: values.space_node_id,
              ...(can('property.house_owner.create')
                ? { owners: values.owners ?? [] }
                : {}),
            }),
        room_no: String(values.room_no).trim(),
        floor_no: values.floor_no ?? null,
        external_code:
          typeof values.external_code === 'string'
            ? values.external_code.trim() || null
            : null,
      });
    } else if (kind === 'space') {
      if (!can(node ? 'property.space.update' : 'property.space.create'))
        throw new Error('没有操作权限');
      await api.saveNode(c, node?.id, {
        ...(node
          ? {}
          : {
              node_type: values.node_type,
              parent_id: values.parent_id === 'root' ? null : values.parent_id,
            }),
        name: String(values.name).trim(),
        external_code:
          typeof values.external_code === 'string'
            ? values.external_code.trim() || null
            : null,
        sort_order: values.sort_order ?? 0,
      });
    } else if (kind === 'owner') {
      if (
        !can(
          owner ? 'property.house_owner.update' : 'property.house_owner.create',
        )
      )
        throw new Error('没有操作权限');
      await api.saveOwner(c, house!.id, owner?.id, {
        name: String(values.name).trim(),
        phone: String(values.phone).trim(),
      });
    } else if (kind === 'house-status') {
      if (!can('property.house.update')) throw new Error('没有操作权限');
      await api.saveHouse(c, house!.id, { enabled: !house!.enabled });
    } else if (kind === 'space-status') {
      if (!can('property.space.update')) throw new Error('没有操作权限');
      await api.saveNode(c, node!.id, { enabled: !node!.enabled });
    } else if (kind === 'owner-status') {
      if (!can('property.house_owner.update')) throw new Error('没有操作权限');
      await api.saveOwner(c, house!.id, owner!.id, {
        enabled: !owner!.enabled,
      });
    } else if (kind === 'basis') {
      if (!can('property.fee_basis.create')) throw new Error('没有操作权限');
      const fresh = await api.bases(c, house!.id, { page: 1, page_size: 1 });
      const expected = latest.data?.items[0]?.version_no ?? 0;
      if ((fresh.items[0]?.version_no ?? 0) !== expected) {
        await latest.refetch();
        throw new Error('计费依据已有新版本，请核对最新依据后重新保存');
      }
      await api.createBasis(c, house!.id, {
        expected_latest_version_no: expected,
        effective_from_month: (values.month as Dayjs).format('YYYY-MM'),
        house_usage: values.house_usage as Usage,
        area_sqm: values.method === 'area' ? String(values.area) : null,
        unit_price_cents:
          values.method === 'area' ? toCents(values.rate) : null,
        fixed_amount_cents:
          values.method === 'fixed' ? toCents(values.fixed) : null,
        change_reason: String(values.reason).trim(),
      });
    }
    await done();
    message.success(
      kind === 'basis'
        ? '新的计费依据版本已保存'
        : kind === 'owner'
          ? '业主登记已保存，列表已更新'
          : '资料已保存',
    );
  };
  const reason = (
    <Form.Item
      name="reason"
      label="变更原因"
      rules={[
        { required: true, whitespace: true, message: '请填写变更原因' },
        { max: 1000 },
      ]}
    >
      <Input.TextArea rows={3} maxLength={1000} showCount />
    </Form.Item>
  );
  return (
    <PropertyEditor
      title={title}
      form={form}
      initial={initial}
      submit={submit}
      close={close}
      readOnly={kind === 'basis-view'}
    >
      {kind === 'house' && (
        <>
          <Alert
            showIcon
            type="info"
            title={`当前小区：${community?.name ?? ''}。房屋创建后归属固定。`}
            description="面积与用途在房屋详情的计费依据中维护。"
            style={{ marginBottom: 22 }}
          />
          <Row gutter={16}>
            <Col span={24}>
              <Form.Item
                name="space_node_id"
                label="所属空间"
                rules={[{ required: true, message: '请选择楼栋或单元' }]}
              >
                <Select
                  showSearch
                  optionFilterProp="label"
                  disabled={!!house}
                  placeholder="请选择所属楼栋或单元"
                  options={spaces
                    .filter((n) => n.node_type !== 'phase')
                    .map((n) => ({
                      value: n.id,
                      label: [...n.ancestors.map((a) => a.name), n.name].join(
                        ' · ',
                      ),
                      disabled: !n.effective_enabled,
                    }))}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="room_no"
                label="房号"
                rules={[
                  { required: true, whitespace: true, message: '请填写房号' },
                  { max: 32 },
                ]}
              >
                <Input placeholder="例如 1201" maxLength={32} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="floor_no" label="所在楼层（选填）">
                <InputNumber
                  min={-32768}
                  max={32767}
                  precision={0}
                  style={{ width: '100%' }}
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="external_code" label="外部房屋编号（选填）">
            <Input maxLength={64} placeholder="用于与物业原系统对应" />
          </Form.Item>
          {!house && can('property.house_owner.create') && (
            <>
              <Divider>初始业主（选填）</Divider>
              <Form.List name="owners">
                {(fields, { add, remove }) => (
                  <>
                    {fields.map((field) => (
                      <Row key={field.key} gutter={12}>
                        <Col span={10}>
                          <Form.Item
                            name={[field.name, 'name']}
                            label="业主姓名"
                            rules={[
                              { required: true, whitespace: true },
                              { max: 80 },
                            ]}
                          >
                            <Input maxLength={80} />
                          </Form.Item>
                        </Col>
                        <Col span={11}>
                          <Form.Item
                            name={[field.name, 'phone']}
                            label="手机号"
                            rules={[{ required: true }, phoneRule]}
                          >
                            <Input maxLength={15} />
                          </Form.Item>
                        </Col>
                        <Col span={3}>
                          <Button
                            type="text"
                            danger
                            style={{ marginTop: 30 }}
                            onClick={() => remove(field.name)}
                          >
                            移除
                          </Button>
                        </Col>
                      </Row>
                    ))}
                    <Button
                      type="dashed"
                      block
                      icon={<PlusOutlined />}
                      onClick={() => add()}
                    >
                      添加初始业主
                    </Button>
                  </>
                )}
              </Form.List>
            </>
          )}
        </>
      )}
      {kind === 'space' && (
        <>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="node_type"
                label="空间类型"
                rules={[{ required: true }]}
              >
                <Select
                  disabled={!!node}
                  options={Object.entries(spaceLabels).map(
                    ([value, label]) => ({ value, label }),
                  )}
                  onChange={() => form.setFieldValue('parent_id', 'root')}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="parent_id"
                label="上级空间"
                rules={[
                  { required: true },
                  {
                    validator: async (_, value) => {
                      const type = form.getFieldValue('node_type') as SpaceType;
                      const parent = spaces.find((s) => s.id === value);
                      if (type === 'phase' && value !== 'root')
                        throw new Error('分区必须直属小区');
                      if (
                        type === 'building' &&
                        value !== 'root' &&
                        parent?.node_type !== 'phase'
                      )
                        throw new Error('楼栋须直属小区或分区');
                      if (type === 'unit' && parent?.node_type !== 'building')
                        throw new Error('单元须直属楼栋');
                    },
                  },
                ]}
              >
                <Select
                  disabled={!!node}
                  options={[
                    ...(nodeType !== 'unit'
                      ? [
                          {
                            value: 'root',
                            label: community?.name ?? '当前小区',
                          },
                        ]
                      : []),
                    ...spaces
                      .filter((n) =>
                        nodeType === 'building'
                          ? n.node_type === 'phase'
                          : nodeType === 'unit'
                            ? n.node_type === 'building'
                            : false,
                      )
                      .map((n) => ({
                        value: n.id,
                        label: [...n.ancestors.map((a) => a.name), n.name].join(
                          ' · ',
                        ),
                        disabled: !n.effective_enabled,
                      })),
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="name"
            label="空间名称"
            rules={[
              { required: true, whitespace: true, message: '请填写空间名称' },
              { max: 80 },
            ]}
          >
            <Input placeholder="例如 4 号楼" maxLength={80} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={16}>
              <Form.Item name="external_code" label="外部编号（选填）">
                <Input maxLength={64} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="sort_order" label="排列顺序">
                <InputNumber min={0} max={2147483647} precision={0} />
              </Form.Item>
            </Col>
          </Row>
        </>
      )}
      {kind === 'owner' && (
        <>
          <Alert
            showIcon
            type="info"
            title="登记业主资料不会自动创建居民账号或授予房屋权限。"
            style={{ marginBottom: 22 }}
          />
          <div
            style={{
              padding: 16,
              background: '#f5f7fc',
              borderRadius: 6,
              marginBottom: 22,
            }}
          >
            <strong>{house?.display_address}</strong>
            <div className="muted">当前房屋业主登记，保存后立即更新列表</div>
          </div>
          <Form.Item
            name="name"
            label="业主姓名"
            rules={[
              { required: true, whitespace: true, message: '请填写业主姓名' },
              { max: 80 },
            ]}
          >
            <Input placeholder="请填写真实姓名" maxLength={80} />
          </Form.Item>
          <Form.Item
            name="phone"
            label="手机号"
            rules={[{ required: true, message: '请填写手机号' }, phoneRule]}
          >
            <Input placeholder="请输入 11 位手机号" maxLength={15} />
          </Form.Item>
        </>
      )}
      {kind.endsWith('-status') && (
        <>
          <Alert
            type="warning"
            showIcon
            title={
              (kind === 'owner-status'
                ? owner
                : kind === 'space-status'
                  ? node
                  : house
              )?.enabled
                ? '停用后保留全部资料及历史记录'
                : '启用后恢复自身可用状态'
            }
            description={
              kind === 'space-status'
                ? '下级房屋与业主登记的实际状态受影响。历史账单、收款及审核记录继续保留。'
                : kind === 'owner-status'
                  ? '停用登记不可用于后续资料匹配。更换业主请新增登记。'
                  : '停用后新增业主、账单及线下收款暂不可用。'
            }
            style={{ marginBottom: 20 }}
          />
          <div style={{ padding: 16, background: '#f6f8fc', borderRadius: 8 }}>
            {node?.name || owner?.name || house?.display_address}
          </div>
        </>
      )}
      {kind === 'basis' && (
        <>
          <Alert
            type="info"
            showIcon
            title="新版本保存后不可修改，已建账单不受影响。"
            style={{ marginBottom: 20 }}
          />
          <QueryError error={latest.error} retry={latest.refetch} />
          <Form.Item name="month" label="生效月份" rules={[{ required: true }]}>
            <DatePicker picker="month" style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="house_usage"
            label="房屋用途"
            rules={[{ required: true }]}
          >
            <Select
              options={Object.entries(usageLabels).map(([value, label]) => ({
                value,
                label,
              }))}
            />
          </Form.Item>
          <Form.Item name="method" label="计费方式">
            <Radio.Group
              options={[
                { value: 'area', label: '面积 × 单价' },
                { value: 'fixed', label: '固定月费' },
              ]}
            />
          </Form.Item>
          {method === 'fixed' ? (
            <Form.Item
              name="fixed"
              label="固定月费（元）"
              rules={[{ required: true }]}
            >
              <InputNumber min={0} precision={2} style={{ width: '100%' }} />
            </Form.Item>
          ) : (
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item
                  name="area"
                  label="建筑面积（㎡）"
                  rules={[{ required: true }]}
                >
                  <InputNumber
                    min={0}
                    max={99999999}
                    precision={4}
                    style={{ width: '100%' }}
                  />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  name="rate"
                  label="月单价（元 / ㎡）"
                  rules={[{ required: true }]}
                >
                  <InputNumber
                    min={0}
                    precision={2}
                    style={{ width: '100%' }}
                  />
                </Form.Item>
              </Col>
            </Row>
          )}
          {reason}
        </>
      )}
      {kind === 'basis-view' && basis && (
        <DetailGrid
          items={[
            ['依据版本', `v${basis.version_no}`],
            ['生效月份', basis.effective_from_month],
            ['房屋用途', usageLabels[basis.house_usage]],
            ['计费标准', basisText(basis)],
            ['变更原因', basis.change_reason],
            ['创建时间', time(basis.created_at)],
          ]}
        />
      )}
    </PropertyEditor>
  );
}
