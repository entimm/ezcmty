import { useEffect, useState } from 'react';
import { Alert, Button, Empty, Space, Spin, Steps, Table, Tag } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { PageHeader, Panel, DetailGrid, Status } from '../ui';
import { useResource } from '../hooks';
import { Stats, ErrorNotice, cents, time } from '../imports/presentation';
import type { FlowPageProps } from '../imports/runtime';
import type { PaymentsRuntime } from './runtime';
import { ActionDialog } from './ActionDialog';
import type { FundsAction } from './ActionDialog';
import { confirmationNames, fundNames, paymentNames } from './presentation';
export function PaymentDetail({
  runtime: r,
  params,
  go,
}: FlowPageProps & { runtime: PaymentsRuntime }) {
  const id = params.id || params.payment_id || '';
  const [sharingPage, setSharingPage] = useState(1);
  const [unfreezePage, setUnfreezePage] = useState(1);
  const [action, setAction] = useState<FundsAction>();
  const [scheduled, setScheduled] = useState(false);
  useEffect(() => {
    setSharingPage(1);
    setUnfreezePage(1);
    setAction(undefined);
    setScheduled(false);
  }, [id]);
  const order = useResource(
    ['payments', 'order', id],
    () => r.api.order(id),
    !!id,
    scheduled ? 2500 : undefined,
  );
  const sharing = useResource(
    ['payments', 'sharing', id, sharingPage],
    () =>
      r.api.sharing({ payment_order_id: id, page: sharingPage, page_size: 20 }),
    !!id && r.can('payment.read'),
    scheduled ? 2500 : undefined,
  );
  const unfreezing = useResource(
    ['payments', 'unfreeze', id, unfreezePage],
    () =>
      r.api.unfreezing({
        payment_order_id: id,
        page: unfreezePage,
        page_size: 20,
      }),
    !!id && r.can('payment.read'),
    scheduled ? 2500 : undefined,
  );
  const refresh = async () => {
    await Promise.all([
      order.refetch(),
      ...(r.can('payment.read')
        ? [sharing.refetch(), unfreezing.refetch()]
        : []),
    ]);
  };
  const back = () => {
    let prior: Record<string, string> = {};
    try {
      prior = JSON.parse(params.return || '{}') as Record<string, string>;
    } catch {
      /* Default list. */
    }
    go('payments', prior);
  };
  if (order.isLoading)
    return (
      <Panel>
        <Spin />
      </Panel>
    );
  const o = order.data;
  if (!o)
    return (
      <>
        <PageHeader title="支付与资金详情" back={back} />
        <ErrorNotice error={order.error} retry={() => void order.refetch()} />
        {!id && <Empty description="未指定支付订单，请返回列表选择记录" />}
      </>
    );
  const paid =
    o.status === 'succeeded' || o.confirmation_status !== 'unconfirmed';
  const posted = o.confirmation_status === 'posted';
  const shareItems =
    sharing.data?.items.flatMap((s) =>
      s.items.map((i) => ({
        ...i,
        execution_order_no: s.order_no,
        order_status: s.status,
      })),
    ) || [];
  const shareFailed =
    shareItems.some((i) => i.result === 'failed') ||
    sharing.data?.items.some((s) => s.status === 'rejected');
  const unfreezeFailed = unfreezing.data?.items.some(
    (x) => x.status === 'failed',
  );
  const allShown =
    sharing.data && sharing.data.total === sharing.data.items.length;
  const allocations = new Map<string, number>();
  const successful = new Map<string, number>();
  shareItems.forEach((i) => {
    allocations.set(i.allocation_id, i.allocation_cents);
    if (i.result === 'success')
      successful.set(
        i.allocation_id,
        (successful.get(i.allocation_id) || 0) + i.amount_cents,
      );
  });
  const shared =
    !!allShown &&
    allocations.size > 0 &&
    [...allocations].every(
      ([key, amount]) => (successful.get(key) || 0) >= amount,
    );
  const unfrozen = !!unfreezing.data?.items.some((u) =>
    ['succeeded', 'no_remaining'].includes(u.status),
  );
  const fundAttention =
    (!shared &&
      (shareFailed ||
        sharing.data?.items.some((x) => x.status === 'unknown'))) ||
    (!unfrozen &&
      (unfreezeFailed ||
        unfreezing.data?.items.some((x) => x.status === 'unknown')));
  const step = !paid ? 0 : !posted ? 1 : !shared ? 2 : !unfrozen ? 3 : 4;
  const outside =
    r.scope === 'property' &&
    o.items.some((i) => i.community_id !== r.communityId);
  return (
    <>
      <PageHeader
        title="支付与资金详情"
        description={`${o.order_no} · ${o.items.map((i) => i.house_label).join('、')}`}
        back={back}
        extra={
          <>
            <Status>{paymentNames[o.status]}</Status>
            <Button icon={<ReloadOutlined />} onClick={() => void refresh()}>
              刷新
            </Button>
            {r.writes &&
              r.can('payment.recover') &&
              (o.status === 'unknown' ||
                o.confirmation_status === 'awaiting_posting' ||
                fundAttention ||
                o.status === 'closing') && (
                <Button
                  type="primary"
                  disabled={scheduled}
                  onClick={() =>
                    setAction({
                      kind: 'recover',
                      id: o.id,
                      token: o.state_token,
                      label: o.order_no,
                    })
                  }
                >
                  {scheduled ? '恢复任务已安排' : '恢复原流程'}
                </Button>
              )}
          </>
        }
      />
      <ErrorNotice error={order.error} />
      {outside && (
        <Alert
          style={{ marginBottom: 20 }}
          showIcon
          type="info"
          title="当前详情按订单的完整账单范围展示；顶部小区选择不会裁剪订单金额与明细。"
        />
      )}
      {scheduled && (
        <Alert
          style={{ marginBottom: 20 }}
          type="info"
          showIcon
          title="恢复任务已安排"
          description="当前事实仍按下方分别显示。受理成功不代表资金成功，须等待可信查询及实际处理结果。"
        />
      )}
      {(o.confirmation_status === 'awaiting_posting' || fundAttention) && (
        <Alert
          style={{ marginBottom: 20 }}
          showIcon
          type="warning"
          title={
            o.confirmation_status === 'awaiting_posting'
              ? '渠道已确认收款，账单尚未入账，禁止重复付款。'
              : '资金处理有异常，居民已确认缴费仍然有效。'
          }
          description={
            r.scope === 'property'
              ? '请联系平台并提供订单号，物业端没有资金恢复权限。'
              : '恢复只继续原业务流程，不提供强制成功、直接清占用或跳过分账。'
          }
        />
      )}
      <Panel title="资金进度" extra={<Tag>四类事实独立确认</Tag>}>
        <Steps
          current={step}
          items={[
            {
              title: '居民支付',
              content: paid ? '已确认收款' : paymentNames[o.status],
              status: paid ? 'finish' : 'process',
            },
            {
              title: '账单入账',
              content: confirmationNames[o.confirmation_status],
              status: posted
                ? 'finish'
                : o.confirmation_status === 'awaiting_posting'
                  ? 'error'
                  : 'wait',
            },
            {
              title: '服务费分账',
              content: !r.can('payment.read')
                ? '无读取权限'
                : shared
                  ? '应分已足额确认'
                  : shareFailed
                    ? '存在执行失败'
                    : '详见逐项结果',
              status: shared ? 'finish' : shareFailed ? 'error' : 'wait',
            },
            {
              title: '剩余资金解冻',
              content: !r.can('payment.read')
                ? '无读取权限'
                : unfrozen
                  ? '渠道已确认'
                  : unfreezeFailed
                    ? '存在执行失败'
                    : '待确认',
              status: unfrozen ? 'finish' : unfreezeFailed ? 'error' : 'wait',
            },
          ]}
        />
        <p style={{ margin: '24px 0 0', color: '#64748b' }}>
          分账异常不会撤销居民已发生的缴费。物业到账金额、渠道手续费只展示可信结果，未知时显示待核对。
        </p>
      </Panel>
      <Stats
        items={[
          ['订单金额', cents(o.amount_cents)],
          ['可信实付', cents(o.payer_total_cents)],
          [
            '服务费应分',
            shared
              ? cents([...allocations.values()].reduce((a, b) => a + b, 0))
              : '详见执行明细',
          ],
          ['渠道手续费', '待核对', '不以订单差额推算'],
        ]}
      />
      <Panel title="支付事实">
        <DetailGrid
          items={[
            ['订单号', o.order_no],
            ['收款商户', o.merchant_name],
            ['收款商户号', o.merchant_no],
            ['支付时间', time(o.paid_at)],
            ['渠道交易号', o.channel_transaction_no || '待确认'],
            [
              '订单状态',
              <Status key="status">{paymentNames[o.status]}</Status>,
            ],
            ['冻结规则ID', o.rule_version_id],
            ['订单创建时间', time(o.created_at)],
          ]}
        />
      </Panel>
      <Panel title="对应账单与入账">
        <Table
          rowKey="id"
          pagination={false}
          dataSource={o.items}
          columns={[
            { title: '房屋', dataIndex: 'house_label' },
            { title: '账期', dataIndex: 'billing_month' },
            { title: '缴纳金额', dataIndex: 'amount_cents', render: cents },
            {
              title: '入账状态',
              render: () => (
                <Status>{confirmationNames[o.confirmation_status]}</Status>
              ),
            },
            ...(r.scope === 'property'
              ? [
                  {
                    title: '操作',
                    render: (_: unknown, i: (typeof o.items)[number]) => (
                      <Button
                        type="link"
                        onClick={() =>
                          go('bills', {
                            id: i.bill_id,
                            community: i.community_id,
                          })
                        }
                      >
                        查看账单
                      </Button>
                    ),
                  },
                ]
              : []),
          ]}
        />
      </Panel>
      <Panel
        title="服务费应分与每次执行"
        extra={<Tag>执行金额不累计为服务费</Tag>}
      >
        <ErrorNotice
          error={sharing.error}
          retry={() => void sharing.refetch()}
        />
        {!r.can('payment.read') ? (
          <Alert type="info" title="当前账号没有读取资金执行记录的权限" />
        ) : (
          <>
            <Table
              rowKey="id"
              loading={sharing.isLoading}
              pagination={false}
              dataSource={shareItems}
              locale={{
                emptyText: posted
                  ? '尚无分账执行记录'
                  : '账单尚未入账，暂无分账执行记录',
              }}
              scroll={{ x: 1000 }}
              columns={[
                { title: '执行单号', dataIndex: 'execution_order_no' },
                { title: '接收方', dataIndex: 'receiver_name' },
                {
                  title: '应分额',
                  dataIndex: 'allocation_cents',
                  render: cents,
                },
                {
                  title: '本次执行额',
                  dataIndex: 'amount_cents',
                  render: cents,
                },
                {
                  title: '本次结果',
                  render: (_, i) => (
                    <Status>
                      {i.result === 'success'
                        ? '渠道确认成功'
                        : i.result === 'failed'
                          ? '执行失败'
                          : fundNames[i.order_status]}
                    </Status>
                  ),
                },
                {
                  title: '说明',
                  dataIndex: 'failure_summary',
                  render: (value) => value || '—',
                },
                { title: '结果时间', dataIndex: 'finished_at', render: time },
              ]}
            />
            {sharing.data && sharing.data.total > 20 && (
              <Space style={{ marginTop: 16 }}>
                <Button
                  disabled={sharingPage === 1}
                  onClick={() => setSharingPage(sharingPage - 1)}
                >
                  上一页
                </Button>
                <span>
                  第 {sharingPage} 页 · 共 {sharing.data.total} 笔执行单
                </span>
                <Button
                  disabled={sharingPage * 20 >= sharing.data.total}
                  onClick={() => setSharingPage(sharingPage + 1)}
                >
                  下一页
                </Button>
              </Space>
            )}
            <p style={{ color: '#64748b', marginTop: 16 }}>
              同一应分额可对应多次执行。请分别核查应分额与成功执行结果，不能将每次尝试金额相加当作服务费。
            </p>
          </>
        )}
      </Panel>
      <Panel title="独立解冻结果">
        <ErrorNotice
          error={unfreezing.error}
          retry={() => void unfreezing.refetch()}
        />
        {r.can('payment.read') && (
          <Table
            rowKey="id"
            loading={unfreezing.isLoading}
            dataSource={unfreezing.data?.items}
            pagination={{
              current: unfreezePage,
              pageSize: 20,
              total: unfreezing.data?.total,
              showSizeChanger: false,
              onChange: setUnfreezePage,
            }}
            columns={[
              { title: '执行单号', dataIndex: 'order_no' },
              {
                title: '处理状态',
                dataIndex: 'status',
                render: (value) => <Status>{fundNames[value]}</Status>,
              },
              {
                title: '渠道确认解冻额',
                dataIndex: 'unfrozen_cents',
                render: cents,
              },
              {
                title: '结果说明',
                dataIndex: 'failure_summary',
                render: (value) => value || '—',
              },
              { title: '确认时间', dataIndex: 'finished_at', render: time },
            ]}
          />
        )}
        <DetailGrid
          items={[
            ['物业实际到账', '待可信结算结果核对'],
            ['渠道手续费', '待可信账单核对'],
          ]}
        />
      </Panel>
      {action && r.writes && (
        <ActionDialog
          action={action}
          close={() => setAction(undefined)}
          setDirty={r.setDirty}
          verify={refresh}
          submit={(reason) =>
            r
              .writes!.recover(action.id, {
                reason,
                expected_state_token: action.token,
              })
              .then((result) => {
                setScheduled(true);
                return result;
              })
          }
        />
      )}
    </>
  );
}
