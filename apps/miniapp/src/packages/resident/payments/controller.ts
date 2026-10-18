import { onSessionReset } from '../../../auth/resident';
import { ApiError, StaleSessionError } from '../../../shared/http/client';
import { requestPayment } from '../../../shared/wechat/payment';
import { ResidentBill } from '../billing/types';
import * as api from './api';
import { clearPending, pending, rememberOrder } from './pending';
import { PaymentOrder } from './types';

export class PaymentController {
  private epoch = 0;
  private busy = false;
  private off = onSessionReset(() => {
    this.pause();
  });
  pause(): void {
    this.epoch++;
    this.busy = false;
  }
  dispose(): void {
    this.pause();
    this.off();
  }
  private current(epoch: number): void {
    if (epoch !== this.epoch) throw new StaleSessionError();
  }
  async create(bill: ResidentBill): Promise<PaymentOrder> {
    if (this.busy) throw new Error('正在核实原支付，请稍候');
    this.busy = true;
    const epoch = this.epoch;
    try {
      if (bill.own_payment_order_id) {
        const result = await api.order(bill.own_payment_order_id);
        this.current(epoch);
        return result;
      }
      const value = pending(bill.id, bill.row_version);
      if (value.orderId) {
        const result = await api.order(value.orderId);
        this.current(epoch);
        return result;
      }
      const result = await api.createOrder(value.data, value.key);
      this.current(epoch);
      rememberOrder(bill.id, value, result.id);
      const current = await api.order(result.id);
      this.current(epoch);
      return current;
    } catch (error) {
      this.current(epoch);
      if (error instanceof ApiError && error.status === 409)
        clearPending(bill.id);
      throw error;
    } finally {
      if (epoch === this.epoch) this.busy = false;
    }
  }
  async pay(
    item: PaymentOrder,
  ): Promise<{ order: PaymentOrder; message: string }> {
    if (this.busy) throw new Error('正在处理原支付，请稍候');
    this.busy = true;
    const epoch = this.epoch;
    try {
      const current = await api.order(item.id);
      this.current(epoch);
      if (!current.available_actions.includes('continue_payment'))
        return { order: current, message: '' };
      const parameters = await api.parameters(item.id);
      this.current(epoch);
      const panel = await requestPayment(parameters.client_parameters);
      this.current(epoch);
      await api.refresh(item.id);
      this.current(epoch);
      const order = await api.order(item.id);
      this.current(epoch);
      return {
        order,
        message:
          panel === 'cancelled'
            ? '已取消本次支付面板，原订单保留，可继续或核实结果'
            : '正在确认缴费结果，请勿重复付款',
      };
    } finally {
      if (epoch === this.epoch) this.busy = false;
    }
  }
}
