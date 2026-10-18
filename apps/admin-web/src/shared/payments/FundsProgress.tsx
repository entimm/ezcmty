import { Alert, Card, Table } from 'antd';
import type { SharingOrder, UnfreezeOrder } from './types';
import { fundsStatuses, money } from './presentation';
export function FundsProgress({
  sharing,
  unfreezing,
}: {
  sharing: SharingOrder[];
  unfreezing: UnfreezeOrder[];
}) {
  return (
    <>
      <Alert
        type="info"
        showIcon
        title="分账与解冻分别确认；渠道手续费以可信账单为准，未知金额待核对。"
      />
      <Card title="服务费应分与每次分账执行">
        <Table
          rowKey="id"
          dataSource={sharing}
          pagination={false}
          columns={[
            { title: '执行单号', dataIndex: 'order_no' },
            {
              title: '状态',
              dataIndex: 'status',
              render: (value: string) => fundsStatuses[value] || value,
            },
          ]}
          expandable={{
            expandedRowRender: (row) => (
              <Table
                rowKey="id"
                dataSource={row.items}
                pagination={false}
                columns={[
                  { title: '接收方', dataIndex: 'receiver_name' },
                  {
                    title: '应分额',
                    dataIndex: 'allocation_cents',
                    render: money,
                  },
                  {
                    title: '本次执行额',
                    dataIndex: 'amount_cents',
                    render: money,
                  },
                  {
                    title: '本次结果',
                    dataIndex: 'result',
                    render: (value: string | null) =>
                      value === 'success'
                        ? '足额成功'
                        : value === 'failed'
                          ? '失败'
                          : '待确认',
                  },
                  { title: '业务说明', dataIndex: 'failure_summary' },
                ]}
              />
            ),
          }}
        />
        <Alert
          type="info"
          title="同一应分可能有多次执行；执行金额不累计为服务费。"
        />
      </Card>
      <Card title="独立解冻结果">
        <Table
          rowKey="id"
          dataSource={unfreezing}
          pagination={false}
          columns={[
            { title: '执行单号', dataIndex: 'order_no' },
            {
              title: '状态',
              dataIndex: 'status',
              render: (value: string) => fundsStatuses[value] || value,
            },
            {
              title: '渠道确认解冻金额',
              dataIndex: 'unfrozen_cents',
              render: money,
            },
            { title: '业务说明', dataIndex: 'failure_summary' },
          ]}
        />
      </Card>
    </>
  );
}
