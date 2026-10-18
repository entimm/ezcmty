import { useState } from 'react';
import { Link, useNavigate, useParams } from '@umijs/max';
import {
  PageContainer,
  ProTable,
  type ProColumns,
} from '@ant-design/pro-components';
import { useQuery } from '@tanstack/react-query';
import { Alert, Button, Card, Descriptions, Space, Spin, Tabs } from 'antd';
import { useAdminApp } from '../../../shared/admin-app-context';
import { useListState } from '../../../shared/hooks/use-list-state';
import { ListEmpty, ReadError } from '../../../components/AdminFeedback';
import { usePropertySession } from '../hooks';
import type { Bill, BillAction, BillOperation, SettlementEntry } from './api';
import { useBillingApi, usePendingBills } from './hooks';
import { BasisProof, BillStatus, PendingBillRecovery } from './BillParts';
import { BillEditor } from './BillEditor';
import { CreateBillDrawer } from './CreateBillDrawer';
import { actionLabels, yuan } from './values';

type Editor = {
  bill: Bill;
  action: Exclude<BillAction, 'create' | 'online_receipt'>;
  entry?: SettlementEntry;
};
function History({
  bill,
  edit,
}: {
  bill: Bill;
  edit: (value: Editor) => void;
}) {
  const api = useBillingApi();
  const { hasPermission } = usePropertySession();
  const state = useListState('entry_');
  const operations = useListState('operation_');
  const tabs = useListState();
  const active =
    tabs.params.get('history') === 'operations' ? 'operations' : 'entries';
  const entries = useQuery({
    queryKey: ['bill-entries', bill.id, state.page, state.pageSize],
    queryFn: () =>
      api.entries(bill.community_id, bill.id, {
        page: state.page,
        page_size: state.pageSize,
      }),
    enabled: active === 'entries',
  });
  const history = useQuery({
    queryKey: [
      'bill-operations',
      bill.id,
      operations.page,
      operations.pageSize,
    ],
    queryFn: () =>
      api.operations(bill.community_id, bill.id, {
        page: operations.page,
        page_size: operations.pageSize,
      }),
    enabled: active === 'operations',
  });
  const entryColumns: ProColumns<SettlementEntry>[] = [
    {
      title: '类型',
      render: (_, row) =>
        row.entry_type === 'reversal'
          ? '冲正'
          : row.reversed_by_entry_id
            ? '收款（已冲正）'
            : '收款',
    },
    { title: '金额', render: (_, row) => yuan(row.amount_cents) },
    {
      title: '来源',
      render: (_, row) =>
        row.source_type === 'online_payment' ? '线上支付' : '线下登记',
    },
    {
      title: '实际收款日',
      render: (_, row) => row.received_on ?? '不详 / 不适用',
    },
    { title: '登记时间', dataIndex: 'created_at', valueType: 'dateTime' },
    {
      title: '操作人',
      render: (_, row) =>
        row.actor_type === 'system' ? '系统' : row.actor_name,
    },
    { title: '原因', render: (_, row) => row.reason ?? '—' },
    {
      title: '关联条目',
      render: (_, row) =>
        row.payment_order_item_id ??
        row.reverses_entry_id ??
        row.reversed_by_entry_id ??
        '—',
      ellipsis: true,
    },
    {
      title: '操作',
      valueType: 'option',
      render: (_, row) =>
        bill.lifecycle_status === 'active' &&
        !bill.payment_in_progress &&
        row.source_type === 'offline' &&
        row.entry_type === 'receipt' &&
        !row.reversed_by_entry_id &&
        hasPermission('property.bill_receipt.correct') ? (
          <Space>
            <Button
              type="link"
              onClick={() =>
                edit({ bill, action: 'correct_receipt', entry: row })
              }
            >
              纠错
            </Button>
            <Button
              type="link"
              onClick={() =>
                edit({ bill, action: 'reverse_receipt', entry: row })
              }
            >
              撤销误登记
            </Button>
          </Space>
        ) : null,
    },
  ];
  const operationColumns: ProColumns<BillOperation>[] = [
    { title: '版本', dataIndex: 'bill_version' },
    { title: '操作', render: (_, row) => actionLabels[row.action] },
    {
      title: '操作人',
      render: (_, row) =>
        row.actor_type === 'system' ? '系统' : row.actor_name,
    },
    { title: '原因', render: (_, row) => row.reason ?? '—' },
    { title: '时间', dataIndex: 'created_at', valueType: 'dateTime' },
    { title: '请求标识', dataIndex: 'request_id', copyable: true },
  ];
  return (
    <Card>
      <Tabs
        activeKey={active}
        onChange={(key) =>
          tabs.update({ history: key === 'entries' ? undefined : key })
        }
        items={[
          {
            key: 'entries',
            label: '收款与冲正流水',
            children: (
              <>
                {entries.isError && (
                  <ReadError
                    error={entries.error}
                    retry={() => void entries.refetch()}
                  />
                )}
                <ProTable<SettlementEntry>
                  rowKey="id"
                  search={false}
                  columns={entryColumns}
                  dataSource={entries.data?.items ?? []}
                  loading={entries.isFetching}
                  pagination={{
                    ...state.pagination,
                    total: entries.data?.total ?? 0,
                  }}
                  scroll={{ x: 1200 }}
                  locale={{ emptyText: <ListEmpty filtered={false} /> }}
                  options={{ reload: () => void entries.refetch() }}
                />
              </>
            ),
          },
          {
            key: 'operations',
            label: '操作历史',
            children: (
              <>
                {history.isError && (
                  <ReadError
                    error={history.error}
                    retry={() => void history.refetch()}
                  />
                )}
                <ProTable<BillOperation>
                  rowKey="id"
                  search={false}
                  columns={operationColumns}
                  dataSource={history.data?.items ?? []}
                  loading={history.isFetching}
                  pagination={{
                    ...operations.pagination,
                    total: history.data?.total ?? 0,
                  }}
                  scroll={{ x: 950 }}
                  locale={{ emptyText: <ListEmpty filtered={false} /> }}
                  options={{ reload: () => void history.refetch() }}
                />
              </>
            ),
          },
        ]}
      />
    </Card>
  );
}
export default function BillDetailPage() {
  const { community_id: communityId = '', bill_id: billId = '' } = useParams<{
    community_id: string;
    bill_id: string;
  }>();
  const api = useBillingApi();
  const { path } = useAdminApp();
  const navigate = useNavigate();
  const { status, hasPermission } = usePropertySession();
  const query = useQuery({
    queryKey: ['bills', 'detail', communityId, billId],
    queryFn: () => api.bill(communityId, billId),
    enabled: status === 'authenticated' && hasPermission('property.bill.read'),
  });
  const [editor, setEditor] = useState<Editor>();
  const [recreating, setRecreating] = useState(false);
  const pending = usePendingBills();
  const bill = query.data;
  const writable = bill?.lifecycle_status === 'active' && !pending.length;
  return (
    <PageContainer
      title={bill ? `${bill.billing_month} 物业费账单` : '账单详情'}
      breadcrumb={{
        items: [
          {
            title: (
              <Link to={path(`/property/communities/${communityId}/bills`)}>
                账单管理
              </Link>
            ),
          },
          { title: '账单详情' },
        ],
      }}
      extra={
        bill && (
          <Space wrap>
            {writable && hasPermission('property.bill.update') && (
              <Button onClick={() => setEditor({ bill, action: 'update' })}>
                修改资料
              </Button>
            )}
            {writable && hasPermission('property.bill_receipt.create') && (
              <Button
                type="primary"
                disabled={
                  !bill.house_effective_enabled ||
                  bill.outstanding_cents === 0 ||
                  bill.payment_in_progress
                }
                onClick={() => setEditor({ bill, action: 'receipt' })}
              >
                登记线下收款
              </Button>
            )}
            {writable && hasPermission('property.bill.void') && (
              <Button
                danger
                disabled={bill.settled_cents !== 0 || bill.payment_in_progress}
                onClick={() => setEditor({ bill, action: 'void' })}
              >
                作废账单
              </Button>
            )}
            {bill.lifecycle_status === 'voided' &&
              hasPermission('property.bill.create') && (
                <Button
                  disabled={!bill.house_effective_enabled || !!pending.length}
                  onClick={() => setRecreating(true)}
                >
                  按此房屋月份新建
                </Button>
              )}
          </Space>
        )
      }
    >
      <PendingBillRecovery />
      {query.isError ? (
        <ReadError error={query.error} retry={() => void query.refetch()} />
      ) : !bill ? (
        <Spin />
      ) : (
        <Space orientation="vertical" size="large" style={{ width: '100%' }}>
          {bill.payment_in_progress && (
            <Alert
              type="warning"
              showIcon
              title="该账单有支付正在处理中"
              description="暂不能登记线下收款、纠错、撤销或作废。请等待支付结果，或由付款人核实原订单。"
            />
          )}
          {!bill.house_effective_enabled && (
            <Alert
              type="info"
              showIcon
              title="房屋或上级已停用，仅允许历史查询、资料修改、收款纠错及符合条件的作废。"
            />
          )}
          {bill.lifecycle_status === 'voided' && (
            <Alert
              type="warning"
              showIcon
              title="账单已作废，只读保留"
              description={bill.void_reason}
            />
          )}
          <Card title="账单概览" extra={<BillStatus bill={bill} />}>
            <Descriptions
              column={{ xs: 1, sm: 2 }}
              items={[
                {
                  key: 'house',
                  label: '房屋位置快照',
                  children: bill.house_label_snapshot,
                  span: 2,
                },
                { key: 'type', label: '账单类型', children: '物业费' },
                {
                  key: 'period',
                  label: '计费期间',
                  children: `${bill.period_start} 至 ${bill.period_end}（不含结束日）`,
                },
                {
                  key: 'receivable',
                  label: '应收',
                  children: yuan(bill.receivable_cents),
                },
                {
                  key: 'settled',
                  label: '已缴',
                  children: yuan(bill.settled_cents),
                },
                {
                  key: 'outstanding',
                  label: '待缴',
                  children: yuan(bill.outstanding_cents),
                },
                {
                  key: 'external',
                  label: '外部编号',
                  children: bill.external_bill_no ?? '—',
                },
                { key: 'due', label: '到期日', children: bill.due_date ?? '—' },
                {
                  key: 'source',
                  label: '金额来源',
                  children:
                    bill.amount_source === 'basis'
                      ? '依据自动计算'
                      : '手动填写',
                },
                {
                  key: 'manual',
                  label: '手填原因',
                  children: bill.manual_amount_reason ?? '—',
                  span: 2,
                },
                {
                  key: 'version',
                  label: '当前版本',
                  children: bill.row_version,
                },
                {
                  key: 'created',
                  label: '建账时间',
                  children: new Date(bill.created_at).toLocaleString(),
                },
                { key: 'id', label: '账单 ID', children: bill.id, span: 2 },
                ...(hasPermission('property.house.read')
                  ? [
                      {
                        key: 'link',
                        label: '房屋资料',
                        children: (
                          <Link
                            to={path(
                              `/property/communities/${communityId}/houses/${bill.house_id}`,
                            )}
                          >
                            查看房屋
                          </Link>
                        ),
                      },
                    ]
                  : []),
              ]}
            />
          </Card>
          <Card
            title={
              bill.amount_source === 'basis' ? '建账时计费依据' : '参考依据'
            }
          >
            {bill.basis ? (
              <BasisProof
                basis={bill.basis}
                extra={
                  bill.amount_source === 'basis'
                    ? `本账单固定引用此版本，计算规则 v${bill.calculation_rule_version}`
                    : '应收以手填金额为准'
                }
              />
            ) : (
              <p>此账单未绑定计费依据。</p>
            )}
          </Card>
          <History
            bill={bill}
            edit={(value) => {
              if (!pending.length) setEditor(value);
            }}
          />
        </Space>
      )}
      {editor && (
        <BillEditor
          key={`${editor.action}-${editor.entry?.id ?? editor.bill.id}`}
          {...editor}
          done={() => setEditor(undefined)}
        />
      )}
      {recreating && bill && (
        <CreateBillDrawer
          communityId={communityId}
          prefill={bill}
          done={(result) => {
            setRecreating(false);
            if (result)
              navigate(
                path(
                  `/property/communities/${communityId}/bills/${result.bill.id}`,
                ),
              );
          }}
        />
      )}
    </PageContainer>
  );
}
