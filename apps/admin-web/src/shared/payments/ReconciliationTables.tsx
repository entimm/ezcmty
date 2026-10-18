import { Button, Card, Form, Input, Select, Table } from 'antd';
import type { TablePaginationConfig } from 'antd';
import type { Discrepancy, Filters, ReconciliationRun } from './types';
import {
  differenceLabels,
  money,
  reconciliationStatuses,
} from './presentation';
export function ReconciliationTables({
  runs,
  differences,
  loadingRuns,
  loadingDifferences,
  runPagination,
  differencePagination,
  filters,
  companyFilter,
  onFilter,
  openRun,
  openDifference,
}: {
  runs: ReconciliationRun[];
  differences: Discrepancy[];
  loadingRuns: boolean;
  loadingDifferences: boolean;
  runPagination: TablePaginationConfig;
  differencePagination: TablePaginationConfig;
  filters: Filters;
  companyFilter?: boolean;
  onFilter: (values: Record<string, string>) => void;
  openRun: (id: string) => void;
  openDifference: (id: string) => void;
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
        {companyFilter && (
          <Form.Item label="公司ID" name="property_company_id">
            <Input allowClear />
          </Form.Item>
        )}
        <Form.Item label="业务日期起" name="business_date_from">
          <Input type="date" />
        </Form.Item>
        <Form.Item label="业务日期止" name="business_date_through">
          <Input type="date" />
        </Form.Item>
        <Form.Item label="账单类型" name="statement_type">
          <Select
            allowClear
            style={{ width: 180 }}
            options={[
              { value: 'trade', label: '收款交易' },
              { value: 'profit_sharing', label: '分账事件' },
              ...(companyFilter
                ? [{ value: 'platform_fundflow', label: '平台资金记账' }]
                : []),
            ]}
          />
        </Form.Item>
        <Button htmlType="submit">查询</Button>
      </Form>
      <Card title="资金核对批次">
        <Table
          rowKey="id"
          dataSource={runs}
          loading={loadingRuns}
          pagination={runPagination}
          scroll={{ x: 1000 }}
          columns={[
            {
              title: '业务日期',
              dataIndex: 'business_date',
              render: (value: string, row: ReconciliationRun) => (
                <Button type="link" onClick={() => openRun(row.id)}>
                  {value}
                </Button>
              ),
            },
            { title: '账单类型', dataIndex: 'statement_type' },
            {
              title: '收款商户',
              dataIndex: 'merchant_no',
              render: (value: string | null) => value || '平台基本账户',
            },
            {
              title: '核对状态',
              dataIndex: 'status',
              render: (value: ReconciliationRun['status']) =>
                reconciliationStatuses[value],
            },
            {
              title: '本地／渠道／匹配／差异',
              key: 'summary',
              render: (_, row) =>
                `${row.summary.local_count} / ${row.summary.channel_count} / ${row.summary.matched_count} / ${row.summary.discrepancy_count}`,
            },
            {
              title: '可信渠道手续费',
              key: 'fee',
              render: (_, row) => money(row.summary.channel_fee_cents),
            },
          ]}
        />
      </Card>
      <Card title="核对差异">
        <Table
          rowKey="id"
          dataSource={differences}
          loading={loadingDifferences}
          pagination={differencePagination}
          scroll={{ x: 1000 }}
          columns={[
            {
              title: '业务引用',
              dataIndex: 'reference_key',
              render: (value: string, row: Discrepancy) => (
                <Button type="link" onClick={() => openDifference(row.id)}>
                  {value}
                </Button>
              ),
            },
            {
              title: '核对维度',
              key: 'check',
              render: (_, row) => row.evidence.check_code,
            },
            {
              title: '差异类型',
              dataIndex: 'difference_type',
              render: (value: Discrepancy['difference_type']) =>
                differenceLabels[value],
            },
            { title: '应有金额', dataIndex: 'expected_cents', render: money },
            { title: '实际金额', dataIndex: 'actual_cents', render: money },
            {
              title: '处置状态',
              dataIndex: 'status',
              render: (value: Discrepancy['status']) =>
                reconciliationStatuses[value],
            },
          ]}
        />
      </Card>
    </>
  );
}
