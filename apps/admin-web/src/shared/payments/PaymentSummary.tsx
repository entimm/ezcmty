import { Card, Descriptions, Table } from 'antd';
import type { PaymentOrder } from './types';
import { confirmationLabels, money, paymentStatuses } from './presentation';
export function PaymentSummary({ item }: { item: PaymentOrder }) {
  return (
    <>
      <Card title="支付事实">
        <Descriptions
          items={[
            { key: 'order', label: '订单号', children: item.order_no },
            {
              key: 'merchant',
              label: '收款商户',
              children: `${item.merchant_name}（${item.merchant_no}）`,
            },
            {
              key: 'status',
              label: '支付状态',
              children: paymentStatuses[item.status],
            },
            {
              key: 'confirmation',
              label: '账单入账',
              children: confirmationLabels[item.confirmation_status],
            },
            {
              key: 'amount',
              label: '订单金额',
              children: money(item.amount_cents),
            },
            {
              key: 'paid',
              label: '可信实付金额',
              children: money(item.payer_total_cents),
            },
            {
              key: 'time',
              label: '支付时间',
              children: item.paid_at
                ? new Date(item.paid_at).toLocaleString()
                : '待确认',
            },
            {
              key: 'transaction',
              label: '渠道交易号',
              children: item.channel_transaction_no || '待确认',
            },
          ]}
        />
      </Card>
      <Card title="对应账单">
        <Table
          rowKey="id"
          pagination={false}
          dataSource={item.items}
          columns={[
            { title: '房屋', dataIndex: 'house_label' },
            { title: '账期', dataIndex: 'billing_month' },
            { title: '缴纳金额', dataIndex: 'amount_cents', render: money },
            { title: '账单编号', dataIndex: 'bill_id' },
          ]}
        />
      </Card>
    </>
  );
}
