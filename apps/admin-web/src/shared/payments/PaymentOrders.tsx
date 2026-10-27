import { DatePicker } from '../DatePicker';
import { useEffect, useState } from 'react';
import dayjs from 'dayjs';
import { dayStartInstant, dayAfterInstant } from '../datetime';
import { Button, Input, Select, Table, Tag } from 'antd';
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { PageHeader, Panel, Status } from '../ui';
import { useResource } from '../hooks';
import { Stats, ErrorNotice, cents, time } from '../imports/presentation';
import type { FlowPageProps } from '../imports/runtime';
import type { PaymentsRuntime } from './runtime';
import type { PaymentOrder } from './types';
import { confirmationNames, paymentNames } from './presentation';
export function PaymentOrders({
  runtime: r,
  page,
  params,
  go,
}: FlowPageProps & { runtime: PaymentsRuntime }) {
  const [search, setSearch] = useState(params.order || '');
  const [searchBy, setSearchBy] = useState(params.by || 'order_no');
  const [status, setStatus] = useState<string | undefined>(params.status);
  const [company, setCompany] = useState<string | undefined>(params.company);
  const [dates, setDates] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(
    params.from && params.to
      ? [dayjs.utc(params.from), dayjs.utc(params.to)]
      : null,
  );
  useEffect(() => {
    setSearch(params.order || '');
    setStatus(params.status);
    setCompany(params.company);
    setDates(
      params.from && params.to
        ? [dayjs.utc(params.from), dayjs.utc(params.to)]
        : null,
    );
  }, [params.order, params.status, params.company, params.from, params.to]);
  const current = Number(params.p) || 1;
  const data = useResource(
    ['payments', 'orders', r.scope, r.communityId, params],
    () =>
      r.api.orders({
        page: current,
        page_size: 20,
        ...(r.scope === 'platform'
          ? { property_company_id: params.company }
          : { community_id: r.communityId || undefined }),
        status: params.status,
        order_no:
          params.by !== 'channel_transaction_no' ? params.order : undefined,
        channel_transaction_no:
          params.by === 'channel_transaction_no' ? params.order : undefined,
        created_from: params.from ? dayStartInstant(params.from) : undefined,
        created_before: params.to ? dayAfterInstant(params.to) : undefined,
      }),
  );
  const companies = useResource(
    ['payments', 'companies'],
    () => r.companies!(),
    r.scope === 'platform' && !!r.companies,
  );
  const items = data.data?.items || [];
  const open = (order: PaymentOrder) =>
    go('payment-detail', { id: order.id, return: JSON.stringify(params) });
  const companyName = (id: string) =>
    companies.data?.find((x) => x.id === id)?.name || id;
  return (
    <>
      <PageHeader
        title={r.scope === 'property' ? '线上收款' : '支付记录'}
        description={
          r.scope === 'property'
            ? '查看本小区居民缴费与资金处理结果。'
            : '在授权范围内核查支付、入账、分账与解冻。'
        }
        extra={
          <Button
            icon={<ReloadOutlined />}
            loading={data.isFetching}
            onClick={() => void data.refetch()}
          >
            刷新记录
          </Button>
        }
      />
      <Stats
        items={[
          [
            '当前页成功订单额',
            cents(
              items
                .filter((x) => x.status === 'succeeded')
                .reduce((sum, x) => sum + BigInt(x.amount_cents), 0n),
            ),
            `${items.filter((x) => x.status === 'succeeded').length} 笔可信支付`,
          ],
          [
            '当前页已入账',
            cents(
              items
                .filter((x) => x.confirmation_status === 'posted')
                .reduce((sum, x) => sum + BigInt(x.amount_cents), 0n),
            ),
            '支付与入账分别确认',
          ],
          [
            '当前页待恢复入账',
            items.filter((x) => x.confirmation_status === 'awaiting_posting')
              .length,
            '请勿重复登记收款',
          ],
          [
            '当前页支付待确认',
            items.filter((x) =>
              ['pending', 'unknown', 'closing'].includes(x.status),
            ).length,
            '按原单查询可信结果',
          ],
        ]}
      />
      <Panel
        title={r.scope === 'property' ? '本小区收款流水' : '支付流水'}
        extra={
          <Tag>
            {r.scope === 'property'
              ? r.community?.name || '当前公司授权范围'
              : '授权平台范围'}
          </Tag>
        }
      >
        <div className="filter-bar">
          {r.scope === 'platform' && (
            <Select
              aria-label="支付公司名称"
              placeholder="全部物业公司"
              loading={companies.isLoading}
              value={company}
              onChange={setCompany}
              allowClear
              showSearch
              optionFilterProp="label"
              options={companies.data?.map((x) => ({
                value: x.id,
                label: x.name,
              }))}
              style={{ width: 240 }}
            />
          )}
          <Select
            aria-label="搜索字段"
            value={searchBy}
            onChange={setSearchBy}
            options={[
              { value: 'order_no', label: '订单号' },
              { value: 'channel_transaction_no', label: '渠道交易号' },
            ]}
            style={{ width: 130 }}
          />
          <Input
            prefix={<SearchOutlined />}
            allowClear
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="输入完整单号精确查询"
            style={{ width: 240 }}
          />
          <Select
            placeholder="全部支付状态"
            allowClear
            value={status}
            onChange={setStatus}
            style={{ width: 150 }}
            options={Object.entries(paymentNames).map(([value, label]) => ({
              value,
              label,
            }))}
          />
          <DatePicker.RangePicker
            value={dates}
            onChange={(values) =>
              setDates(values?.[0] && values[1] ? [values[0], values[1]] : null)
            }
          />
          <Button
            type="primary"
            onClick={() =>
              go(page, {
                order: search.trim() || undefined,
                by: searchBy,
                status,
                company,
                from: dates?.[0].format('YYYY-MM-DD'),
                to: dates?.[1].format('YYYY-MM-DD'),
              })
            }
          >
            查询
          </Button>
          <Button
            onClick={() => {
              setSearch('');
              setStatus(undefined);
              setCompany(undefined);
              setDates(null);
              go(page);
            }}
          >
            重置
          </Button>
        </div>
        <ErrorNotice error={data.error} retry={() => void data.refetch()} />
        <ErrorNotice error={companies.error} />
        <Table<PaymentOrder>
          rowKey="id"
          dataSource={items}
          loading={data.isLoading}
          pagination={{
            current,
            pageSize: 20,
            total: data.data?.total,
            showSizeChanger: false,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (p) => go(page, { ...params, p: String(p) }),
          }}
          scroll={{ x: 1100 }}
          columns={[
            {
              title: '订单 / 房屋',
              render: (_, item) => (
                <>
                  <Button
                    type="link"
                    style={{ padding: 0 }}
                    onClick={() => open(item)}
                  >
                    {item.order_no}
                  </Button>
                  <div style={{ color: '#64748b', fontSize: 12, marginTop: 4 }}>
                    {item.items.map((x) => x.house_label).join('、') || '—'}
                  </div>
                </>
              ),
            },
            ...(r.scope === 'platform'
              ? [
                  {
                    title: '收款公司',
                    dataIndex: 'property_company_id',
                    render: companyName,
                  },
                ]
              : []),
            {
              title: '账期',
              render: (_, item) =>
                item.items.map((x) => x.billing_month).join('、'),
            },
            {
              title: '金额',
              dataIndex: 'amount_cents',
              render: cents,
              align: 'right',
            },
            {
              title: '支付',
              dataIndex: 'status',
              render: (value) => (
                <Status>
                  {paymentNames[value as keyof typeof paymentNames]}
                </Status>
              ),
            },
            {
              title: '入账',
              dataIndex: 'confirmation_status',
              render: (value) => (
                <Status>
                  {confirmationNames[value as keyof typeof confirmationNames]}
                </Status>
              ),
            },
            {
              title: '资金处理',
              render: (_, item) => (
                <Button type="link" onClick={() => open(item)}>
                  查看实际结果
                </Button>
              ),
            },
            {
              title: '支付时间',
              dataIndex: 'paid_at',
              render: (value) => (value ? time(value) : '待确认'),
            },
            {
              title: '操作',
              render: (_, item) => (
                <Button type="link" onClick={() => open(item)}>
                  查看详情
                </Button>
              ),
            },
          ]}
        />
      </Panel>
    </>
  );
}
