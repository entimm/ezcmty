import type { ReactNode } from 'react';
import { Alert, Button, Empty } from 'antd';
import dayjs from 'dayjs';
import { money, Status } from '../ui';
import type { Bill, HousingRecord, FeeBasis } from './types';
export { businessToday, formatTime as time } from '../datetime';

export const usageLabels = {
  residential: '住宅',
  commercial: '商业',
  office: '办公',
  other: '其他',
};
export const actionLabels = {
  create: '创建物业费账单',
  update: '修改账单资料',
  receipt: '登记线下收款',
  online_receipt: '系统线上收款入账',
  correct_receipt: '收款登记纠错',
  reverse_receipt: '撤销收款登记',
  void: '作废账单',
};
export const cents = (value: number | null | undefined) =>
  value === null || value === undefined ? '—' : money(value / 100);
export const date = (value: string | null | undefined) =>
  value ? dayjs.utc(value).format('YYYY-MM-DD') : '—';
export function toCents(value: unknown, positive = false) {
  const raw = String(value ?? '').trim();
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(raw))
    throw new Error('请输入非负金额，最多两位小数');
  const [whole, fraction = ''] = raw.split('.');
  const result = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'));
  if (result > BigInt(Number.MAX_SAFE_INTEGER))
    throw new Error('金额超出支持范围');
  if (positive && result === 0n) throw new Error('收款金额须大于 0');
  return Number(result);
}
export function billStatus(bill: Bill) {
  return bill.lifecycle_status === 'voided'
    ? '已作废'
    : bill.settlement_status === 'settled'
      ? '已缴清'
      : bill.settlement_status === 'partially_settled'
        ? '部分已缴'
        : '待缴费';
}
export function HousingStatus({ record }: { record: HousingRecord }) {
  return (
    <Status>
      {!record.enabled
        ? '已停用'
        : record.effective_enabled
          ? '已启用'
          : '上级停用'}
    </Status>
  );
}
export function basisText(basis?: FeeBasis | null) {
  return !basis
    ? '未设置'
    : basis.fixed_amount_cents !== null
      ? `固定月费 ${cents(basis.fixed_amount_cents)}`
      : `${basis.area_sqm ?? '—'} ㎡ × ${cents(basis.unit_price_cents)} / ㎡`;
}
export function QueryError({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => unknown;
}) {
  if (!error) return null;
  return (
    <Alert
      showIcon
      type="error"
      title="资料读取失败"
      description={error instanceof Error ? error.message : '请稍后重试'}
      style={{ marginBottom: 20 }}
      action={
        retry && (
          <Button size="small" onClick={() => void retry()}>
            重试
          </Button>
        )
      }
    />
  );
}
export function SelectCommunity() {
  return (
    <Empty
      style={{ padding: '80px 0' }}
      description="请先在顶部业务范围栏选择小区，继续办理相关业务"
    />
  );
}
export function Metrics({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
        gap: 18,
        marginBottom: 22,
      }}
    >
      {children}
    </div>
  );
}
export function Metric({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: ReactNode;
  sub: ReactNode;
  color?: string;
}) {
  return (
    <div
      style={{
        background: '#fff',
        border: '1px solid #e8ecf3',
        borderRadius: 12,
        padding: '19px 22px',
        boxShadow: '0 2px 6px #20365b03',
      }}
    >
      <div style={{ color: '#728098', fontSize: 13 }}>{label}</div>
      <div
        style={{
          fontSize: 28,
          fontWeight: 650,
          fontVariantNumeric: 'tabular-nums',
          letterSpacing: '-0.5px',
          margin: '9px 0',
          color: color ?? '#243856',
        }}
      >
        {value}
      </div>
      <div style={{ color: '#8c97a8', fontSize: 12 }}>{sub}</div>
    </div>
  );
}
