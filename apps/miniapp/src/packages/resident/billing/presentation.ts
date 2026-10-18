import { ResidentBill } from './types';

export const money = (cents: number) => (cents / 100).toFixed(2);
export const availability: Record<
  ResidentBill['payment_availability'],
  string
> = {
  available: '缴纳全部待缴金额',
  own_payment_in_progress: '继续处理原支付',
  other_payment_in_progress: '其他缴费人正在处理中，请等待结果',
  settled: '账单已结清',
  voided: '账单已作废',
  collection_unavailable: '收款配置暂不可用，请联系物业',
};
export const entryLabels = {
  own_payment: '本人缴纳',
  other_payment: '其他缴费人缴纳',
  offline_receipt: '线下登记',
  offline_adjustment: '线下登记调整',
};
