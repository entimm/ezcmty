import { PaymentOrder } from './types';
export function paymentLabel(order: PaymentOrder): string {
  if (order.status === 'succeeded' && order.confirmation_status === 'posted')
    return '缴费成功';
  if (order.confirmation_status === 'awaiting_posting')
    return '收款已确认，缴费正在确认，请勿重复付款';
  if (order.status === 'closed') return '支付已确认关闭';
  if (order.status === 'closing') return '正在核实并关闭原订单，请勿重复付款';
  if (order.status === 'pending') return '正在准备支付，请稍候';
  if (order.available_actions.includes('continue_payment'))
    return '待支付，可继续原订单';
  return '结果确认中，请勿重复付款';
}
export const paymentUrl = (id: string) =>
  '/packages/resident/pages/payment-detail/index?id=' + encodeURIComponent(id);
