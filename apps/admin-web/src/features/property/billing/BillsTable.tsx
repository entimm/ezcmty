import { useState } from 'react';
import { Link, useNavigate } from '@umijs/max';
import { ProTable, type ProColumns } from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Button, Card, Drawer, Form, Input, Select, Space, Tabs } from 'antd';
import { useAdminApp } from '../../../shared/admin-app-context';
import { useListState } from '../../../shared/hooks/use-list-state';
import { ListEmpty, ReadError } from '../../../components/AdminFeedback';
import { usePropertySession } from '../hooks';
import type { House } from '../housing/api';
import { useHousingApi } from '../housing/hooks';
import { SpaceBranch } from '../housing/SpaceTree';
import type { Bill } from './api';
import { useBillingApi, usePendingBills } from './hooks';
import { BillStatus, PendingBillRecovery } from './BillParts';
import { CreateBillDrawer } from './CreateBillDrawer';
import { HousePicker } from './HousePicker';
import { yuan } from './values';

interface SearchValues {
  house_id?: string;
  billing_month_from?: string;
  billing_month_to?: string;
  external_bill_no?: string;
  settlement_status?: string;
  due_date_from?: string;
  due_date_to?: string;
  is_overdue?: string;
  sort?: string;
}
const sortOptions = [
  { value: '-period_start', label: '月份从新到旧' },
  { value: 'period_start', label: '月份从旧到新' },
  { value: '-created_at', label: '最近建账' },
  { value: 'created_at', label: '最早建账' },
  { value: 'due_date', label: '到期日从早到晚' },
  { value: '-due_date', label: '到期日从晚到早' },
  { value: '-receivable_cents', label: '应收从多到少' },
  { value: 'receivable_cents', label: '应收从少到多' },
  { value: '-outstanding_cents', label: '待缴从多到少' },
  { value: 'outstanding_cents', label: '待缴从少到多' },
];
export function BillsTable({
  communityId,
  house,
  enabled = true,
}: {
  communityId: string;
  house?: House;
  enabled?: boolean;
}) {
  const api = useBillingApi();
  const housing = useHousingApi();
  const [choosingSpace, setChoosingSpace] = useState(false);
  const { path } = useAdminApp();
  const navigate = useNavigate();
  const { status, hasPermission } = usePropertySession();
  const state = useListState(house ? 'bill_' : '');
  const [creating, setCreating] = useState(false);
  const pending = usePendingBills();
  const view = ['all', 'voided'].includes(state.params.get('view') ?? '')
    ? state.params.get('view')!
    : 'pending';
  const filters = {
    page: state.page,
    page_size: state.pageSize,
    house_id: house?.id ?? state.params.get('house_id') ?? undefined,
    space_node_id: state.params.get('space_node_id') || undefined,
    billing_month_from: state.params.get('billing_month_from') || undefined,
    billing_month_to: state.params.get('billing_month_to') || undefined,
    lifecycle_status: view === 'voided' ? 'voided' : 'active',
    outstanding_only: view === 'pending',
    settlement_status:
      view === 'all'
        ? state.params.get('settlement_status') || undefined
        : undefined,
    external_bill_no: state.params.get('external_bill_no') || undefined,
    due_date_from: state.params.get('due_date_from') || undefined,
    due_date_to: state.params.get('due_date_to') || undefined,
    is_overdue: ['true', 'false'].includes(state.params.get('is_overdue') ?? '')
      ? state.params.get('is_overdue') === 'true'
      : undefined,
    sort: sortOptions.some((item) => item.value === state.params.get('sort'))
      ? state.params.get('sort')!
      : '-period_start',
  };
  const query = useQuery({
    queryKey: ['bills', 'list', communityId, filters],
    queryFn: () => api.bills(communityId, filters),
    enabled: status === 'authenticated' && hasPermission('property.bill.read'),
  });
  const selectedSpace = useQuery({
    queryKey: ['spaces', 'detail', communityId, filters.space_node_id],
    queryFn: () => housing.node(communityId, filters.space_node_id!),
    enabled: !!filters.space_node_id && hasPermission('property.space.read'),
  });
  const columns: ProColumns<Bill>[] = [
    { title: '房屋', dataIndex: 'house_label_snapshot', width: 240 },
    { title: '月份', dataIndex: 'billing_month' },
    { title: '应收', render: (_, row) => yuan(row.receivable_cents) },
    { title: '已缴', render: (_, row) => yuan(row.settled_cents) },
    { title: '待缴', render: (_, row) => yuan(row.outstanding_cents) },
    { title: '状态', render: (_, row) => <BillStatus bill={row} /> },
    { title: '外部编号', render: (_, row) => row.external_bill_no ?? '—' },
    { title: '到期日', render: (_, row) => row.due_date ?? '—' },
    {
      title: '操作',
      valueType: 'option',
      render: (_, row) => (
        <Link to={path(`/property/communities/${communityId}/bills/${row.id}`)}>
          账单详情
        </Link>
      ),
    },
  ];
  const fields = [
    'house_id',
    'space_node_id',
    'billing_month_from',
    'billing_month_to',
    'external_bill_no',
    'settlement_status',
    'due_date_from',
    'due_date_to',
    'is_overdue',
    'sort',
  ] as const;
  return (
    <>
      {house && <PendingBillRecovery />}
      {!house && hasPermission('property.space.read') && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Space wrap>
            <span>
              空间范围：
              {selectedSpace.data
                ? [
                    ...selectedSpace.data.ancestors.map((item) => item.name),
                    selectedSpace.data.name,
                  ].join('／')
                : (filters.space_node_id ?? '全部房屋')}
            </span>
            <Button onClick={() => setChoosingSpace(true)}>按空间选择</Button>
            {filters.space_node_id && (
              <Button
                onClick={() =>
                  state.update({ space_node_id: undefined, page: 1 })
                }
              >
                清除空间筛选
              </Button>
            )}
          </Space>
          {selectedSpace.isError && (
            <ReadError
              error={selectedSpace.error}
              retry={() => void selectedSpace.refetch()}
            />
          )}
        </Card>
      )}
      {choosingSpace && (
        <Drawer
          open
          title="选择空间范围"
          size={420}
          onClose={() => setChoosingSpace(false)}
        >
          <div role="tree" aria-label="账单空间范围">
            <SpaceBranch
              communityId={communityId}
              selectedId={filters.space_node_id}
              restorePath={
                selectedSpace.data
                  ? [
                      ...selectedSpace.data.ancestors.map((item) => item.id),
                      selectedSpace.data.id,
                    ]
                  : []
              }
              onSelect={(item) => {
                state.update({ space_node_id: item.id, page: 1 });
                setChoosingSpace(false);
              }}
            />
          </div>
        </Drawer>
      )}
      <Card style={{ marginBottom: 16 }}>
        <Tabs
          activeKey={view}
          onChange={(key) =>
            state.update({
              view: key === 'pending' ? undefined : key,
              settlement_status: undefined,
              page: 1,
            })
          }
          items={[
            { key: 'pending', label: '待缴账单' },
            { key: 'all', label: '全部有效' },
            { key: 'voided', label: '已作废' },
          ]}
        />
        <Form<SearchValues>
          key={JSON.stringify(filters)}
          layout="inline"
          initialValues={{
            ...filters,
            is_overdue:
              filters.is_overdue === undefined
                ? undefined
                : String(filters.is_overdue),
          }}
          onFinish={(values) => state.update({ ...values, page: 1 })}
        >
          {!house && hasPermission('property.house.read') && (
            <Form.Item name="house_id" label="房屋">
              <HousePicker communityId={communityId} />
            </Form.Item>
          )}
          <Form.Item name="billing_month_from" label="月份从">
            <Input type="month" />
          </Form.Item>
          <Form.Item name="billing_month_to" label="至">
            <Input type="month" />
          </Form.Item>
          <Form.Item name="external_bill_no" label="外部编号">
            <Input allowClear style={{ width: 160 }} />
          </Form.Item>
          {view === 'all' && (
            <Form.Item name="settlement_status" label="结清状态">
              <Select
                allowClear
                style={{ width: 120 }}
                options={[
                  { value: 'unpaid', label: '待缴' },
                  { value: 'partially_settled', label: '部分已缴' },
                  { value: 'settled', label: '已结清' },
                ]}
              />
            </Form.Item>
          )}
          <Form.Item name="due_date_from" label="到期日从">
            <Input type="date" />
          </Form.Item>
          <Form.Item name="due_date_to" label="至">
            <Input type="date" />
          </Form.Item>
          {view !== 'voided' && (
            <Form.Item name="is_overdue" label="逾期">
              <Select
                allowClear
                style={{ width: 110 }}
                options={[
                  { value: 'true', label: '已逾期' },
                  { value: 'false', label: '未逾期' },
                ]}
              />
            </Form.Item>
          )}
          <Form.Item name="sort" label="排序">
            <Select style={{ width: 160 }} options={sortOptions} />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                查询
              </Button>
              <Button
                onClick={() =>
                  state.update({
                    ...Object.fromEntries(
                      fields.map((field) => [field, undefined]),
                    ),
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
      <ProTable<Bill>
        rowKey="id"
        headerTitle="物业费账单"
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
                view === 'pending' ||
                fields.some((field) => !!state.params.get(field))
              }
            />
          ),
        }}
        toolBarRender={() =>
          hasPermission('property.bill.create')
            ? [
                <Button
                  key="create"
                  type="primary"
                  disabled={!enabled || !!pending.length}
                  onClick={() => setCreating(true)}
                >
                  新增账单
                </Button>,
              ]
            : []
        }
      />
      {creating && (
        <CreateBillDrawer
          communityId={communityId}
          house={house}
          done={(result) => {
            setCreating(false);
            if (result)
              navigate(
                path(
                  `/property/communities/${communityId}/bills/${result.bill.id}`,
                ),
              );
          }}
        />
      )}
    </>
  );
}
