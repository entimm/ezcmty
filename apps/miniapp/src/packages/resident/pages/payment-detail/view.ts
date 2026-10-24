import {
  canContinuePayment,
  hasUncertainPayment,
} from '../../../../core/payments';
import { currentCredential, onSessionReset } from '../../../../core/session';
import { ResidentBill, PaymentOrder } from '../../../../core/types';

const panelMessages = new Map<string, string>();
onSessionReset(() => panelMessages.clear());
const panelKey = (id: string) => `${currentCredential()?.userId || ''}:${id}`;
export function rememberPanelMessage(id: string, message: string): void {
  panelMessages.set(panelKey(id), message);
}
export const panelMessage = (id: string): string =>
  panelMessages.get(panelKey(id)) || '';

export function billPresentation(bill: ResidentBill) {
  const paid =
    bill.payment_availability === 'settled' || bill.outstanding_cents === 0;
  const voided = bill.lifecycle_status === 'voided';
  const own = bill.payment_availability === 'own_payment_in_progress';
  const hints: Record<ResidentBill['payment_availability'], string> = {
    available: '本次需付清此账单全部待缴金额。',
    own_payment_in_progress: '你有一笔原订单尚未结束，请继续处理原订单。',
    other_payment_in_progress: '该账单有支付正在处理中，请稍后查看。',
    settled: '账单已结清，无需再次缴费。',
    voided: '账单已作废，无需缴费。',
    collection_unavailable: '物业暂未开通在线收款，请联系物业。',
  };
  return {
    paid,
    label: voided
      ? '已作废'
      : paid
        ? '已结清'
        : bill.is_overdue
          ? '历史欠费'
          : '待缴',
    tone: voided ? 'gray' : paid ? 'ok' : bill.is_overdue ? 'wait' : '',
    hint: hints[bill.payment_availability],
    warning: !['available', 'own_payment_in_progress', 'settled'].includes(
      bill.payment_availability,
    ),
    canPay:
      !paid &&
      !voided &&
      ['available', 'own_payment_in_progress'].includes(
        bill.payment_availability,
      ),
    button: own
      ? '继续处理原订单'
      : bill.payment_availability === 'other_payment_in_progress'
        ? '支付处理中'
        : bill.payment_availability === 'collection_unavailable'
          ? '暂不可在线缴费'
          : voided
            ? '账单已作废'
            : '前往缴费',
  };
}

export function paymentPresentation(order: PaymentOrder, message = '') {
  const posted =
    order.status === 'succeeded' && order.confirmation_status === 'posted';
  const received = order.confirmation_status === 'awaiting_posting';
  const closed = order.status === 'closed';
  const canPay = !received && !posted && !closed && canContinuePayment(order);
  const cancelled = canPay && message.startsWith('已取消');
  let title = '正在确认支付结果';
  let description = '暂未收到可信支付结果。请核实原订单，请勿重复付款。';
  let icon = 'clock-3';
  let tone = 'wait';
  if (posted) {
    title = '缴费成功';
    description = '收款及账单入账已完成，缴费记录已保存。';
    icon = 'circle-check';
    tone = 'ok';
  } else if (received) {
    title = '已收款，正在确认缴费';
    description = '服务端已确认收款，正在完成入账。此时不能再次付款。';
    icon = 'shield-check';
  } else if (closed) {
    title = '原订单已确认关闭';
    description = '本订单不可继续支付。返回账单重新读取余额后，可再次缴费。';
    icon = 'circle-slash';
    tone = '';
  } else if (order.status === 'closing') {
    title = '正在核实并关闭原订单';
    description = '结果确认前不会重新创建支付，请耐心等待。';
  } else if (canPay) {
    title = cancelled ? '已取消本次支付面板' : '等待支付';
    description = cancelled
      ? '原订单已保留。可继续支付或核实并关闭，请勿另建订单。'
      : '请在订单有效期内完成支付，可安全继续原订单。';
    icon = 'wallet';
    tone = '';
  } else if (
    order.status === 'pending' &&
    !message &&
    !hasUncertainPayment(order)
  ) {
    title = '正在准备支付';
    description = '原订单正在处理中，请稍后核实结果，请勿重复付款。';
  }
  return {
    title,
    description,
    icon,
    tone,
    posted,
    closed,
    canPay,
    canRefresh:
      !posted && !closed && order.available_actions.includes('refresh'),
    canClose:
      !posted &&
      !closed &&
      !received &&
      order.available_actions.includes('close'),
    label: posted ? '缴费成功' : closed ? '已关闭' : '待确认',
    labelTone: posted ? 'ok' : closed ? 'gray' : 'wait',
  };
}
