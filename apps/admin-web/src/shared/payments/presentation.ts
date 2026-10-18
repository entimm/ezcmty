export function money(value: number | null): string {
  return value === null ? '待核对' : `¥${(value / 100).toFixed(2)}`;
}
export function percent(bps: number): string {
  return `${(bps / 100).toFixed(2)}%`;
}
export function parsePercent(input: string): number {
  if (!/^\d{1,3}(?:\.\d{1,2})?$/.test(input.trim()))
    throw new Error('比例须为0至100之间、最多两位小数的百分数');
  const [whole, decimal = ''] = input.trim().split('.');
  const bps = Number(whole) * 100 + Number(decimal.padEnd(2, '0'));
  if (bps > 10000) throw new Error('比例不能超过100%');
  return bps;
}
export function estimateSharing(cents: number, bps: number): number {
  if (
    !Number.isSafeInteger(cents) ||
    cents < 0 ||
    !Number.isInteger(bps) ||
    bps < 0 ||
    bps > 10000
  )
    throw new Error('金额或比例无效');
  return Number((BigInt(cents) * BigInt(bps) + 5000n) / 10000n);
}
export const paymentStatuses = {
  pending: '正在创建',
  unknown: '结果待确认',
  payable: '待支付',
  closing: '核实关闭中',
  succeeded: '缴费成功',
  closed: '已确认关闭',
};
export const confirmationLabels = {
  unconfirmed: '收款未确认',
  awaiting_posting: '已收款待入账',
  posted: '账单已入账',
};
export const configurationReasons: Record<string, string> = {
  company_disabled: '公司已停用',
  merchant_missing: '未激活收款商户',
  rule_missing: '缺少服务费规则',
  merchant_unverified: '商户待核验',
  receiver_unready: '平台接收关系未就绪',
  ratio_unknown: '渠道比例上限待核验',
  ratio_exceeded: '规则超过渠道比例上限',
  channel_unavailable: '渠道暂不可用',
};
export const fundsStatuses: Record<string, string> = {
  pending: '待执行',
  unknown: '结果待确认',
  processing: '处理中',
  finished: '执行结束，详见逐项结果',
  rejected: '已拒绝',
  succeeded: '渠道确认成功',
  failed: '执行失败',
  no_remaining: '渠道确认无剩余可解冻金额',
};
export const differenceLabels = {
  channel_only: '仅渠道存在',
  local_only: '仅本地存在',
  amount_mismatch: '金额不符',
  status_mismatch: '状态不符',
  unclassified: '待分类',
};
export const reconciliationStatuses = {
  ready: '等待核对',
  running: '核对中',
  completed: '核对完成',
  failed: '核对未完成',
  open: '待处理',
  observing: '恢复后待核对',
  resolved: '差异已解决',
};
