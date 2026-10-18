import { Button, Form, Input, Select, Space, Table } from 'antd';
import type { TablePaginationConfig } from 'antd';
import type { Filters, PaymentOrder } from './types';
import { confirmationLabels, money, paymentStatuses } from './presentation';
export function PaymentOrdersTable({
  items,
  loading,
  pagination,
  filters,
  companyFilter,
  onFilter,
  open,
}: {
  items: PaymentOrder[];
  loading: boolean;
  pagination: TablePaginationConfig;
  filters: Filters;
  companyFilter?: boolean;
  onFilter: (values: Record<string, string>) => void;
  open: (id: string) => void;
}) {
  return (
    <>
      <Form
        key={JSON.stringify(filters)}
        layout="inline"
        initialValues={filters}
        onFinish={onFilter}
        style={{ gap: 8, marginBottom: 16 }}
      >
        {(companyFilter ? [['property_company_id', '公司ID']] : [])
          .concat([
            ['community_id', '小区ID'],
            ['house_id', '房屋ID'],
            ['order_no', '订单号'],
            ['channel_transaction_no', '渠道交易号'],
          ])
          .map(([name, label]) => (
            <Form.Item key={name} name={name} label={label}>
              <Input allowClear />
            </Form.Item>
          ))}
        <Form.Item name="status" label="支付状态">
          <Select
            allowClear
            style={{ width: 150 }}
            options={Object.entries(paymentStatuses).map(([value, label]) => ({
              value,
              label,
            }))}
          />
        </Form.Item>
        <Form.Item name="confirmation_status" label="确认状态">
          <Select
            allowClear
            style={{ width: 160 }}
            options={Object.entries(confirmationLabels).map(
              ([value, label]) => ({ value, label }),
            )}
          />
        </Form.Item>
        <Form.Item name="created_from" label="创建起始时间">
          <Input placeholder="2026-10-01T00:00:00+08:00" />
        </Form.Item>
        <Form.Item name="created_before" label="创建截止时间">
          <Input placeholder="带时区时间，不包含该时刻" />
        </Form.Item>
        <Button htmlType="submit">查询</Button>
      </Form>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={items}
        pagination={pagination}
        scroll={{ x: 1000 }}
        columns={[
          {
            title: '订单号',
            dataIndex: 'order_no',
            render: (value: string, row: PaymentOrder) => (
              <Button type="link" onClick={() => open(row.id)}>
                {value}
              </Button>
            ),
          },
          { title: '收款物业', dataIndex: 'merchant_name' },
          { title: '金额', dataIndex: 'amount_cents', render: money },
          {
            title: '房屋与账期',
            key: 'bills',
            render: (_, row) => (
              <Space orientation="vertical">
                {row.items.map((item) => (
                  <span key={item.id}>
                    {item.house_label} · {item.billing_month}
                  </span>
                ))}
              </Space>
            ),
          },
          {
            title: '支付',
            dataIndex: 'status',
            render: (value: PaymentOrder['status']) => paymentStatuses[value],
          },
          {
            title: '入账',
            dataIndex: 'confirmation_status',
            render: (value: PaymentOrder['confirmation_status']) =>
              confirmationLabels[value],
          },
        ]}
      />
    </>
  );
}
