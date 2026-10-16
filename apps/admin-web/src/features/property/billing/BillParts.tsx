import { useState, type ReactNode, type ComponentProps } from 'react';
import { Link } from '@umijs/max';
import { Alert, Button, Card, Descriptions, Input, Space, Tag } from 'antd';
import { useAdminApp } from '../../../shared/admin-app-context';
import { removePending } from '../../../shared/pending-requests';
import { ApiError } from '../../../shared/request-client';
import { OperationError } from '../../../components/AdminFeedback';
import { usePropertySession } from '../hooks';
import type { Bill, FeeBasis } from './api';
import { useBillingApi, useBillingWrite, usePendingBills } from './hooks';
import { usageLabels, yuan } from './values';

export function ReasonInput(props: ComponentProps<typeof Input.TextArea>) {
  return (
    <Input.TextArea
      {...props}
      rows={3}
      count={{
        show: true,
        max: 1000,
        strategy: (text) => [...text.trim()].length,
      }}
    />
  );
}
export function BillStatus({ bill }: { bill: Bill }) {
  return (
    <Space wrap>
      {bill.lifecycle_status === 'voided' ? (
        <Tag color="default">已作废</Tag>
      ) : (
        <Tag
          color={
            bill.settlement_status === 'settled' ? 'success' : 'processing'
          }
        >
          {
            {
              unpaid: '待缴',
              partially_settled: '部分已缴',
              settled: '已结清',
            }[bill.settlement_status ?? 'unpaid']
          }
        </Tag>
      )}
      {bill.is_overdue && <Tag color="warning">已过到期日</Tag>}
    </Space>
  );
}
export function BasisProof({
  basis,
  extra,
}: {
  basis: FeeBasis;
  extra?: ReactNode;
}) {
  return (
    <Descriptions
      size="small"
      column={{ xs: 1, sm: 2 }}
      items={[
        { key: 'version', label: '依据版本', children: `v${basis.version_no}` },
        {
          key: 'month',
          label: '生效月份',
          children: basis.effective_from_month,
        },
        {
          key: 'usage',
          label: '房屋用途',
          children: usageLabels[basis.house_usage],
        },
        { key: 'area', label: '面积（㎡）', children: basis.area_sqm ?? '—' },
        {
          key: 'rate',
          label: '每㎡月单价',
          children:
            basis.unit_price_cents === null
              ? '—'
              : yuan(basis.unit_price_cents),
        },
        {
          key: 'fixed',
          label: '固定月金额',
          children:
            basis.fixed_amount_cents === null
              ? '未设置'
              : yuan(basis.fixed_amount_cents),
        },
        {
          key: 'rule',
          label: '计算方式',
          span: 'filled',
          children:
            basis.fixed_amount_cents !== null
              ? `固定金额 ${yuan(basis.fixed_amount_cents)}`
              : `${basis.area_sqm} ㎡ × ${yuan(basis.unit_price_cents ?? 0)}/㎡，最终四舍五入到分`,
        },
        {
          key: 'reason',
          label: '变更原因',
          children: basis.change_reason,
          span: 'filled',
        },
        ...(extra
          ? [
              {
                key: 'extra',
                label: '说明',
                children: extra,
                span: 'filled' as const,
              },
            ]
          : []),
      ]}
    />
  );
}
export function PendingBillRecovery() {
  const pending = usePendingBills();
  const api = useBillingApi();
  const writer = useBillingWrite();
  const { scope, session } = usePropertySession();
  const { path } = useAdminApp();
  const [checking, setChecking] = useState<string>();
  const [message, setMessage] = useState('');
  const [error, setError] = useState<unknown>();
  const [resolved, setResolved] = useState<Bill>();
  const busy = !!checking || writer.isPending;
  return (
    <>
      {!!pending.length && (
        <Card title="待核实的账单操作" style={{ marginBottom: 16 }}>
          <Alert
            type="warning"
            showIcon
            title="请求结果尚未确认，请先核实或使用原请求重试"
            description="请勿重新登记同一笔业务。页面刷新后仍可核实；同键重试会返回首次成功结果。"
          />
          <OperationError error={error ?? writer.error} />
          {message && <p role="status">{message}</p>}
          {pending.map((item) => (
            <Space
              key={item.key}
              wrap
              style={{ display: 'flex', marginTop: 12 }}
            >
              <span>
                {item.label} · {new Date(item.submittedAt).toLocaleString()}
              </span>
              <Button
                loading={checking === item.key}
                disabled={busy}
                onClick={async () => {
                  setChecking(item.key);
                  setError(undefined);
                  setMessage('');
                  try {
                    const result = await api.result(item.key);
                    if (session)
                      removePending(scope, session.subjectId, item.key);
                    setResolved(result.result.bill);
                    await writer.invalidate();
                  } catch (caught) {
                    if (caught instanceof ApiError && caught.status === 404)
                      setMessage(
                        '暂未查到已提交结果。原请求可能仍在处理，可稍后核实或同键重试。',
                      );
                    else setError(caught);
                  } finally {
                    setChecking(undefined);
                  }
                }}
              >
                核实结果
              </Button>
              <Button
                disabled={busy}
                onClick={async () => {
                  setError(undefined);
                  setMessage('');
                  try {
                    const result = await writer.mutateAsync({
                      submission: item,
                      recovery: item,
                    });
                    setResolved(result.bill);
                  } catch {
                    /* Error is rendered above. */
                  }
                }}
              >
                同键重试原请求
              </Button>
            </Space>
          ))}
        </Card>
      )}
      {resolved && (
        <Alert
          type="success"
          showIcon
          style={{ marginBottom: 16 }}
          title="操作已确认"
          description={
            <Link
              to={path(
                `/property/communities/${resolved.community_id}/bills/${resolved.id}`,
              )}
            >
              查看账单当前详情
            </Link>
          }
        />
      )}
    </>
  );
}
