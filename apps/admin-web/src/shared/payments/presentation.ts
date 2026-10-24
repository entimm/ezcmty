export const paymentNames = {
  pending: '正在创建',
  unknown: '结果待确认',
  payable: '待支付',
  closing: '核实关闭中',
  succeeded: '支付成功',
  closed: '已确认关闭',
};
export const confirmationNames = {
  unconfirmed: '收款未确认',
  awaiting_posting: '已收款待入账',
  posted: '已入账',
};
export const fundNames: Record<string, string> = {
  pending: '待执行',
  unknown: '结果待确认',
  processing: '处理中',
  finished: '执行结束，详见逐项结果',
  rejected: '已拒绝',
  succeeded: '渠道确认成功',
  failed: '执行失败',
  no_remaining: '渠道确认无剩余可解冻金额',
};
export const reconciliationNames: Record<string, string> = {
  ready: '等待核对',
  running: '核对中',
  completed: '已完成',
  failed: '核对未完成',
  open: '待处理',
  observing: '恢复后待核对',
  resolved: '已解决',
};
export const differenceNames: Record<string, string> = {
  channel_only: '仅渠道存在',
  local_only: '仅本地存在',
  amount_mismatch: '金额不符',
  status_mismatch: '状态不符',
  unclassified: '待分类',
};
export const statementNames: Record<string, string> = {
  trade: '交易账单',
  profit_sharing: '分账账单',
  platform_fundflow: '平台资金账单',
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
export function basisPoints(value: number | null | undefined) {
  return value === null || value === undefined
    ? '待核验'
    : `${(value / 100).toFixed(2)}%`;
}
