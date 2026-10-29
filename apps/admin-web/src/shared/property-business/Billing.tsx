import { usePropertyQuery as useQuery } from './queries';
import { DatePicker } from '../DatePicker';
import { useEffect, useState } from 'react';
import {
  ArrowRightOutlined,
  DownloadOutlined,
  EllipsisOutlined,
  PlusOutlined,
  SearchOutlined,
  WalletOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Dropdown,
  Empty,
  Input,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Timeline,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dayjs, { type Dayjs } from 'dayjs';
import { usePropertyBusiness } from './runtime';
import { DetailGrid, PageHeader, Panel, Status } from '../ui';
import {
  type Bill,
  type BillOperation,
  type Filters,
  type SettlementEntry,
} from './types';
import {
  actionLabels,
  basisText,
  billStatus,
  cents,
  Metric,
  Metrics,
  QueryError,
  SelectCommunity,
  time,
} from './presentation';
import { BillModal } from './BillModal';
import { BillingBasisDialog } from './BillingBasis';
export { BillModal } from './BillModal';

type BillAction = 'edit' | 'receipt' | 'correct' | 'reverse' | 'void';
export interface BillEditorState {
  action: BillAction;
  bill: Bill;
  entry?: SettlementEntry;
}
export function BillList({
  houseId,
  filters = {},
  page: outerPage,
  size: outerSize,
  onPage,
  editor: onEditor,
}: {
  houseId?: string;
  filters?: Filters;
  page?: number;
  size?: number;
  onPage?: (page: number, size: number) => void;
  editor?: (editor: BillEditorState) => void;
}) {
  const { api, can, communityId, params, go } = usePropertyBusiness();
  const c = communityId || params.community_id || '';
  const [localPage, setLocalPage] = useState(1);
  const [localSize, setLocalSize] = useState(20);
  const [editor, setEditor] = useState<BillEditorState>();
  const page = outerPage ?? localPage;
  const size = outerSize ?? localSize;
  const list = useQuery({
    queryKey: ['property-business', 'bills', c, houseId, filters, page, size],
    queryFn: () =>
      api.bills(c, { ...filters, house_id: houseId, page, page_size: size }),
    enabled: !!c && can('bill.read'),
  });
  const openEditor = onEditor || setEditor;
  const columns: ColumnsType<Bill> = [
    {
      title: '房屋 / 账期',
      width: 240,
      render: (_, bill) => (
        <div>
          <a
            onClick={() =>
              go('bill-detail', {
                community_id: bill.community_id,
                bill_id: bill.id,
              })
            }
          >
            {bill.house_label_snapshot}
          </a>
          <div className="muted" style={{ fontSize: 12, marginTop: 5 }}>
            {bill.billing_month} · 物业服务费
          </div>
        </div>
      ),
    },
    {
      title: '应收金额',
      width: 125,
      align: 'right',
      render: (_, bill) => (
        <span className="money-number">{cents(bill.receivable_cents)}</span>
      ),
    },
    {
      title: '已缴金额',
      width: 125,
      align: 'right',
      render: (_, bill) => (
        <span className="money-number" style={{ color: '#657188' }}>
          {cents(bill.settled_cents)}
        </span>
      ),
    },
    {
      title: '待缴金额',
      width: 125,
      align: 'right',
      render: (_, bill) => (
        <span
          className="money-number"
          style={{
            color:
              bill.outstanding_cents > 0 && bill.lifecycle_status !== 'voided'
                ? '#c77716'
                : '#7b8798',
          }}
        >
          {bill.lifecycle_status === 'voided'
            ? '—'
            : cents(bill.outstanding_cents)}
        </span>
      ),
    },
    {
      title: '状态',
      width: 130,
      render: (_, bill) => (
        <Space orientation="vertical" size={4}>
          <Status>{billStatus(bill)}</Status>
          {bill.payment_in_progress && <Tag color="blue">支付处理中</Tag>}
          {bill.is_overdue && <Tag color="orange">已逾期</Tag>}
        </Space>
      ),
    },
    {
      title: '到期日期',
      width: 120,
      dataIndex: 'due_date',
      render: (value: string | null) => value || '未设置',
    },
    {
      title: '操作',
      width: 130,
      fixed: 'right',
      render: (_, bill) => (
        <Space size={2}>
          <Button
            type="link"
            size="small"
            onClick={() =>
              go('bill-detail', {
                community_id: bill.community_id,
                bill_id: bill.id,
              })
            }
          >
            详情
          </Button>
          {can('bill_receipt.create') &&
            bill.lifecycle_status === 'active' &&
            bill.outstanding_cents > 0 && (
              <Tooltip
                title={
                  bill.payment_in_progress
                    ? '居民支付正在处理中，请等待原订单结果'
                    : !bill.house_effective_enabled
                      ? '房屋或上级已停用，暂不能登记收款'
                      : undefined
                }
              >
                <Button
                  type="link"
                  size="small"
                  disabled={
                    bill.payment_in_progress || !bill.house_effective_enabled
                  }
                  onClick={() => openEditor({ action: 'receipt', bill })}
                >
                  登记
                </Button>
              </Tooltip>
            )}
        </Space>
      ),
    },
  ];
  return (
    <>
      <QueryError error={list.error} retry={list.refetch} />
      <Table<Bill>
        size="middle"
        rowKey="id"
        dataSource={list.data?.items}
        columns={columns}
        loading={list.isPending}
        pagination={{
          current: page,
          pageSize: size,
          total: list.data?.total,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 条`,
          onChange: (next, nextSize) =>
            onPage
              ? onPage(next, nextSize)
              : (setLocalPage(next), setLocalSize(nextSize)),
        }}
        scroll={{ x: 1030 }}
        locale={{ emptyText: <Empty description="没有符合条件的账单" /> }}
        style={{ marginTop: 20 }}
      />
      {editor && (
        <BillModal editor={editor} close={() => setEditor(undefined)} />
      )}
    </>
  );
}

export function BillingPage({ detail = false }: { detail?: boolean }) {
  const { api, can, communityId, community, params, go } =
    usePropertyBusiness();
  const c = communityId || params.community_id || '';
  const id = params.bill_id || params.id || '';
  const page = Number(params.page) || 1;
  const size = Number(params.page_size) || 20;
  const tab = params.bill_tab || 'pending';
  const [search, setSearch] = useState(params.external_bill_no || '');
  const [status, setStatus] = useState<string | undefined>(
    params.settlement_status,
  );
  const [months, setMonths] = useState<[Dayjs, Dayjs] | null>(
    params.billing_month_from && params.billing_month_to
      ? [
          dayjs.utc(params.billing_month_from),
          dayjs.utc(params.billing_month_to),
        ]
      : null,
  );
  const [dates, setDates] = useState<[Dayjs, Dayjs] | null>(
    params.due_date_from && params.due_date_to
      ? [dayjs.utc(params.due_date_from), dayjs.utc(params.due_date_to)]
      : null,
  );
  const [editor, setEditor] = useState<BillEditorState>();
  const [create, setCreate] = useState(false);
  const [basisOpen, setBasisOpen] = useState(false);
  useEffect(() => {
    if (!detail && params.action === 'new-bill' && c && can('bill.manage'))
      setCreate(true);
  }, [params.action, c, detail, can]);
  const closeCreate = () => {
    setCreate(false);
    if (params.action === 'new-bill')
      go('bills', { ...params, action: undefined });
  };
  const billQuery = useQuery({
    queryKey: ['property-business', 'bill', c, id],
    queryFn: () => api.bill(c, id),
    enabled: !!c && !!id && detail && can('bill.read'),
  });
  const bill = billQuery.data;
  const pageSummary = useQuery({
    queryKey: ['property-business', 'bill-page-summary', c, params],
    queryFn: () =>
      api.bills(c, { ...listFilters(params, tab), page, page_size: size }),
    enabled: !!c && !detail && can('bill.read'),
  });
  const current = pageSummary.data?.items ?? [];
  if (!c)
    return (
      <>
        <PageHeader
          title="物业费账单"
          description="看清每一笔应收与实收，及时处理待缴账单。"
        />
        <SelectCommunity />
      </>
    );
  return (
    <div className="property-pages">
      {detail ? (
        <>
          <PageHeader
            title={bill ? `${bill.billing_month} 物业费账单` : '账单详情'}
            description={
              bill
                ? `${bill.house_label_snapshot} · ${bill.external_bill_no || bill.id}`
                : '读取账单资料'
            }
            back={() => go('bills')}
            extra={
              bill && (
                <>
                  <Status>{billStatus(bill)}</Status>
                  {bill.lifecycle_status === 'active' && (
                    <>
                      {can('bill.manage') && (
                        <Button
                          onClick={() => setEditor({ action: 'edit', bill })}
                        >
                          编辑资料
                        </Button>
                      )}
                      {can('bill_receipt.create') &&
                        bill.outstanding_cents > 0 && (
                          <Tooltip
                            title={
                              bill.payment_in_progress ||
                              !bill.house_effective_enabled
                                ? '支付处理中或房屋已停用，暂不能登记收款'
                                : ''
                            }
                          >
                            <Button
                              type="primary"
                              disabled={
                                bill.payment_in_progress ||
                                !bill.house_effective_enabled
                              }
                              icon={<WalletOutlined />}
                              onClick={() =>
                                setEditor({ action: 'receipt', bill })
                              }
                            >
                              登记线下收款
                            </Button>
                          </Tooltip>
                        )}
                      {can('bill.void') && (
                        <Dropdown
                          menu={{
                            items: [
                              {
                                key: 'void',
                                label: '作废账单',
                                danger: true,
                                disabled:
                                  bill.settled_cents !== 0 ||
                                  bill.payment_in_progress,
                                onClick: () =>
                                  setEditor({ action: 'void', bill }),
                              },
                            ],
                          }}
                        >
                          <Button icon={<EllipsisOutlined />} />
                        </Dropdown>
                      )}
                    </>
                  )}
                  {bill.lifecycle_status === 'voided' && can('bill.manage') && (
                    <Button
                      type="primary"
                      disabled={!bill.house_effective_enabled}
                      onClick={() => setCreate(true)}
                    >
                      按原账单重新建账
                    </Button>
                  )}
                </>
              )
            }
          />
          <QueryError error={billQuery.error} retry={billQuery.refetch} />
          {billQuery.isPending && <Spin />}
          {bill && <BillDetail bill={bill} edit={setEditor} />}
        </>
      ) : (
        <>
          <PageHeader
            title="物业费账单"
            description="看清每一笔应收与实收，及时处理待缴账单。"
            extra={
              <>
                <Button onClick={() => setBasisOpen(true)}>
                  计费依据与试算
                </Button>
                {can('bill.manage') && (
                  <Button
                    icon={<DownloadOutlined />}
                    onClick={() => go('import-new', { import_type: 'bills' })}
                  >
                    批量导入
                  </Button>
                )}
                {can('bill.manage') && (
                  <Button
                    type="primary"
                    icon={<PlusOutlined />}
                    disabled={community?.enabled === false}
                    onClick={() => setCreate(true)}
                  >
                    新增账单
                  </Button>
                )}
              </>
            }
          />
          <Metrics>
            <Metric
              label="本页应收"
              value={
                pageSummary.isSuccess
                  ? cents(
                      current.reduce((sum, b) => sum + b.receivable_cents, 0),
                    )
                  : '—'
              }
              sub="当前查询页 · 有效业务数据"
            />
            <Metric
              label="本页已缴"
              value={
                pageSummary.isSuccess
                  ? cents(current.reduce((sum, b) => sum + b.settled_cents, 0))
                  : '—'
              }
              sub="含线上支付与线下登记"
              color="#237c63"
            />
            <Metric
              label="本页待缴"
              value={
                pageSummary.isSuccess
                  ? cents(
                      current
                        .filter((b) => b.lifecycle_status === 'active')
                        .reduce((sum, b) => sum + b.outstanding_cents, 0),
                    )
                  : '—'
              }
              sub={`${current.filter((b) => b.outstanding_cents > 0 && b.lifecycle_status === 'active').length} 笔账单待缴`}
              color="#ca812a"
            />
            <Metric
              label="本页支付处理中"
              value={
                pageSummary.isSuccess
                  ? current.filter((b) => b.payment_in_progress).length
                  : '—'
              }
              sub="处理期间暂停线下资金操作"
            />
          </Metrics>
          <Panel>
            <Tabs
              activeKey={tab}
              onChange={(next) => {
                setStatus(undefined);
                go('bills', {
                  ...params,
                  bill_tab: next,
                  settlement_status: undefined,
                  page: '1',
                });
              }}
              items={[
                { key: 'pending', label: '待缴账单' },
                { key: 'all', label: '全部有效账单' },
                { key: 'voided', label: '已作废' },
              ]}
            />
            <div
              className="filter-bar"
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 12,
                alignItems: 'center',
              }}
            >
              <Input
                allowClear
                prefix={<SearchOutlined />}
                placeholder="输入完整外部账单编号"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{ width: 240 }}
              />
              <DatePicker.RangePicker
                picker="month"
                placeholder={['账期开始', '账期结束']}
                value={months}
                onChange={(value) => setMonths(value as [Dayjs, Dayjs] | null)}
                style={{ width: 240 }}
              />
              <Select
                allowClear
                value={status}
                onChange={setStatus}
                placeholder="全部结清状态"
                disabled={tab === 'voided'}
                style={{ width: 150 }}
                options={[
                  { value: 'unpaid', label: '待缴费' },
                  { value: 'partially_settled', label: '部分已缴' },
                  { value: 'settled', label: '已缴清' },
                ]}
              />
              <DatePicker.RangePicker
                placeholder={['到期日起', '到期日止']}
                value={dates}
                onChange={(value) => setDates(value as [Dayjs, Dayjs] | null)}
                style={{ width: 250 }}
              />
              <Space style={{ marginLeft: 'auto' }}>
                <Button
                  type="primary"
                  onClick={() =>
                    go('bills', {
                      ...params,
                      page: '1',
                      external_bill_no: search.trim() || undefined,
                      settlement_status: status,
                      billing_month_from: months?.[0].format('YYYY-MM'),
                      billing_month_to: months?.[1].format('YYYY-MM'),
                      due_date_from: dates?.[0].format('YYYY-MM-DD'),
                      due_date_to: dates?.[1].format('YYYY-MM-DD'),
                    })
                  }
                >
                  查询
                </Button>
                <Button
                  onClick={() => {
                    setSearch('');
                    setStatus(undefined);
                    setMonths(null);
                    setDates(null);
                    go('bills', { community_id: c, bill_tab: tab });
                  }}
                >
                  重置
                </Button>
              </Space>
            </div>
            <BillList
              filters={listFilters(params, tab)}
              page={page}
              size={size}
              onPage={(next, nextSize) =>
                go('bills', {
                  ...params,
                  page: String(next),
                  page_size: String(nextSize),
                })
              }
              editor={setEditor}
            />
          </Panel>
        </>
      )}
      {editor && (
        <BillModal editor={editor} close={() => setEditor(undefined)} />
      )}
      {basisOpen && <BillingBasisDialog onClose={() => setBasisOpen(false)} />}
      {create && (
        <BillModal original={detail ? bill : undefined} close={closeCreate} />
      )}
    </div>
  );
}

function listFilters(params: Record<string, string>, tab: string): Filters {
  return {
    lifecycle_status: tab === 'voided' ? 'voided' : 'active',
    outstanding_only: tab === 'pending',
    settlement_status: tab === 'voided' ? undefined : params.settlement_status,
    billing_month_from: params.billing_month_from,
    billing_month_to: params.billing_month_to,
    due_date_from: params.due_date_from,
    due_date_to: params.due_date_to,
    external_bill_no: params.external_bill_no,
    sort: '-period_start',
  };
}

function BillDetail({
  bill,
  edit,
}: {
  bill: Bill;
  edit: (editor: BillEditorState) => void;
}) {
  const { api, can, go } = usePropertyBusiness();
  const [entryPage, setEntryPage] = useState(1);
  const [operationPage, setOperationPage] = useState(1);
  const entries = useQuery({
    queryKey: [
      'property-business',
      'bill-entries',
      bill.community_id,
      bill.id,
      entryPage,
    ],
    queryFn: () =>
      api.entries(bill.community_id, bill.id, {
        page: entryPage,
        page_size: 20,
      }),
  });
  const operations = useQuery({
    queryKey: [
      'property-business',
      'bill-operations',
      bill.community_id,
      bill.id,
      operationPage,
    ],
    queryFn: () =>
      api.operations(bill.community_id, bill.id, {
        page: operationPage,
        page_size: 20,
      }),
  });
  return (
    <>
      {bill.payment_in_progress && (
        <Alert
          showIcon
          type="warning"
          title="居民支付正在处理中"
          description="请等待原支付订单确认。期间暂停线下收款、收款纠错、撤销及作废，避免重复收款。"
          style={{ marginBottom: 22 }}
        />
      )}
      {bill.lifecycle_status === 'voided' && (
        <Alert
          showIcon
          type="info"
          title="账单已作废，只读保留"
          description={`作废原因：${bill.void_reason || '—'}`}
          style={{ marginBottom: 22 }}
        />
      )}
      <Metrics>
        <Metric
          label="应收金额"
          value={cents(bill.receivable_cents)}
          sub="金额创建后保持不变"
        />
        <Metric
          label="已缴金额"
          value={cents(bill.settled_cents)}
          sub="线上 / 线下收款净额"
          color="#237c63"
        />
        <Metric
          label="待缴金额"
          value={
            bill.lifecycle_status === 'voided'
              ? '—'
              : cents(bill.outstanding_cents)
          }
          sub={
            bill.lifecycle_status === 'voided'
              ? '已作废，不再催缴'
              : `到期日期 ${bill.due_date || '未设置'}`
          }
          color="#ca812a"
        />
      </Metrics>
      <div
        className="bill-detail-layout"
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) 310px',
          gap: 20,
        }}
      >
        <div>
          <Panel
            title="账单资料"
            extra={
              can('housing.read') && (
                <Button
                  type="link"
                  size="small"
                  onClick={() =>
                    go('house-detail', {
                      community_id: bill.community_id,
                      house_id: bill.house_id,
                    })
                  }
                >
                  查看房屋档案 <ArrowRightOutlined />
                </Button>
              )
            }
          >
            <DetailGrid
              items={[
                ['房屋位置', bill.house_label_snapshot],
                ['账单月份', bill.billing_month],
                ['收费项目', '物业服务费'],
                [
                  '金额来源',
                  bill.amount_source === 'basis'
                    ? '计费依据自动计算'
                    : '手动填写',
                ],
                [
                  '计费标准',
                  bill.amount_source === 'basis'
                    ? basisText(bill.basis)
                    : bill.manual_amount_reason || '人工确认金额',
                ],
                ['外部编号', bill.external_bill_no || '未填写'],
                ['到期日期', bill.due_date || '未设置'],
                ['创建时间', time(bill.created_at)],
              ]}
            />
          </Panel>
          <div style={{ height: 20 }} />
          <Panel
            title="收款流水"
            extra={
              <span className="muted" style={{ fontSize: 12 }}>
                冲正记录完整保留
              </span>
            }
          >
            <QueryError error={entries.error} retry={entries.refetch} />
            <Table<SettlementEntry>
              size="middle"
              rowKey="id"
              dataSource={entries.data?.items}
              loading={entries.isPending}
              pagination={{
                current: entryPage,
                pageSize: 20,
                total: entries.data?.total,
                onChange: setEntryPage,
              }}
              scroll={{ x: 680 }}
              columns={[
                {
                  title: '收款金额',
                  render: (_, entry) => (
                    <span
                      className="money-number"
                      style={{
                        color: entry.reversed_by_entry_id
                          ? '#9ba4b4'
                          : '#243856',
                        textDecoration: entry.reversed_by_entry_id
                          ? 'line-through'
                          : undefined,
                      }}
                    >
                      {cents(entry.amount_cents)}
                    </span>
                  ),
                },
                {
                  title: '收款来源',
                  render: (_, entry) => (
                    <div>
                      {entry.source_type === 'online_payment'
                        ? '线上支付'
                        : '线下收款'}
                      <div className="muted" style={{ fontSize: 12 }}>
                        {entry.received_on || '日期不详'}
                      </div>
                    </div>
                  ),
                },
                {
                  title: '状态',
                  render: (_, entry) => (
                    <Status>
                      {entry.entry_type === 'reversal'
                        ? '冲正条目'
                        : entry.reversed_by_entry_id
                          ? '已冲正'
                          : '已入账'}
                    </Status>
                  ),
                },
                { title: '经办人', dataIndex: 'actor_name' },
                {
                  title: '操作',
                  render: (_, entry) =>
                    !entry.reversed_by_entry_id &&
                    entry.entry_type === 'receipt' &&
                    entry.source_type === 'offline' &&
                    can('bill_receipt.correct') &&
                    bill.lifecycle_status === 'active' ? (
                      <Space>
                        <Button
                          type="link"
                          size="small"
                          disabled={bill.payment_in_progress}
                          onClick={() =>
                            edit({ action: 'correct', bill, entry })
                          }
                        >
                          纠错
                        </Button>
                        <Button
                          type="link"
                          size="small"
                          danger
                          disabled={bill.payment_in_progress}
                          onClick={() =>
                            edit({ action: 'reverse', bill, entry })
                          }
                        >
                          撤销登记
                        </Button>
                      </Space>
                    ) : (
                      <span className="muted">
                        {entry.source_type === 'online_payment'
                          ? '系统收款'
                          : '—'}
                      </span>
                    ),
                },
              ]}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="暂无收款记录"
                  />
                ),
              }}
            />
          </Panel>
        </div>
        <Panel title="操作记录">
          <QueryError error={operations.error} retry={operations.refetch} />
          <Spin spinning={operations.isPending}>
            <Timeline
              items={(operations.data?.items ?? []).map(
                (operation: BillOperation, i) => ({
                  color: i === 0 ? '#4668df' : '#cdd5e3',
                  children: (
                    <>
                      <div
                        style={{
                          fontSize: 13,
                          lineHeight: 1.7,
                          color: '#42516a',
                        }}
                      >
                        {operation.actor_name} ·{' '}
                        {actionLabels[operation.action]}
                        {operation.reason && <div>{operation.reason}</div>}
                      </div>
                      <div
                        className="muted"
                        style={{ fontSize: 12, marginTop: 4 }}
                      >
                        {time(operation.created_at)}
                      </div>
                    </>
                  ),
                }),
              )}
            />
            {operations.data && operations.data.total > operationPage * 20 && (
              <Button
                type="link"
                onClick={() => setOperationPage(operationPage + 1)}
              >
                查看更早记录
              </Button>
            )}
            {operationPage > 1 && (
              <Button type="link" onClick={() => setOperationPage(1)}>
                返回最新记录
              </Button>
            )}
          </Spin>
        </Panel>
      </div>
    </>
  );
}
