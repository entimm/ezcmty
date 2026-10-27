import { onContextReset } from '../../core/identities';
import { readStored, writeStored, removeStored } from './storage';
import * as api from './api';
import { newKey } from '../../core/ids';
import {
  ApiError,
  isUnknownResult,
  StaleSessionError,
} from '../../core/request';
import { authenticatedUserId, restoreSession } from '../../core/session';
import {
  ClientParameters,
  PaymentInput,
  PaymentOrder,
  ResidentBill,
} from './types';

interface PendingPayment {
  key: string;
  data: PaymentInput;
  orderId?: string;
}
export type PanelResult = 'success' | 'cancelled' | 'unknown';
function normalizePending(
  value: unknown,
  billId: string,
): PendingPayment | undefined {
  const item = value as Partial<PendingPayment> | null;
  if (
    !item ||
    typeof item.key !== 'string' ||
    !/^[A-Za-z0-9_-]{1,128}$/.test(item.key) ||
    !Array.isArray(item.data?.items) ||
    item.data.items.length !== 1 ||
    item.data.items[0].bill_id !== billId ||
    !Number.isSafeInteger(item.data.items[0].expected_row_version) ||
    item.data.items[0].expected_row_version < 1 ||
    (item.orderId !== undefined && typeof item.orderId !== 'string')
  )
    return undefined;
  return {
    key: item.key,
    data: {
      items: [
        {
          bill_id: billId,
          expected_row_version: item.data.items[0].expected_row_version,
        },
      ],
    },
    ...(item.orderId ? { orderId: item.orderId } : {}),
  };
}
function scopedKey(kind: 'bill' | 'uncertain', id: string): string {
  return ':' + kind + ':' + id;
}
function save(key: string, value: unknown): void {
  writeStored('resident-payment', key, value);
}
function remove(key: string): void {
  try {
    removeStored('resident-payment', key);
  } catch {
    /* A retained recovery must still be checked against the server. */
  }
}
function readPending(billId: string): PendingPayment | null {
  return readStored('resident-payment', scopedKey('bill', billId), (value) =>
    normalizePending(value, billId),
  );
}
function uncertain(id: string): boolean {
  return (
    readStored('resident-payment', scopedKey('uncertain', id), (value) =>
      value === true ? true : undefined,
    ) === true
  );
}
function remember(billId: string, value: PendingPayment): void {
  save(scopedKey('bill', billId), value);
}

function terminal(item: PaymentOrder): boolean {
  return (
    item.status === 'closed' ||
    (item.status === 'succeeded' && item.confirmation_status === 'posted')
  );
}
export function reconcilePaymentOrder(item: PaymentOrder): PaymentOrder {
  if (terminal(item)) {
    remove(scopedKey('uncertain', item.id));
    item.items.forEach((part) => {
      try {
        const value = readPending(part.bill_id);
        if (value?.orderId === item.id) remove(scopedKey('bill', part.bill_id));
      } catch {
        /* A cleanup failure must not hide trusted posting or closing facts. */
      }
    });
  }
  return item;
}
export function canContinuePayment(item: PaymentOrder): boolean {
  if (terminal(item)) return false;
  if (
    item.confirmation_status === 'awaiting_posting' ||
    !item.available_actions.some((action) => action === 'continue_payment')
  )
    return false;
  try {
    return !uncertain(item.id);
  } catch {
    return false;
  }
}
export function hasUncertainPayment(item: PaymentOrder): boolean {
  if (terminal(item)) return false;
  try {
    return !!uncertain(item.id);
  } catch {
    return true;
  }
}

export function requestPayment(
  parameters: ClientParameters['client_parameters'],
): Promise<PanelResult> {
  return new Promise((resolve) => {
    try {
      wx.requestPayment({
        ...parameters,
        success: () => resolve('success'),
        fail: (error) =>
          resolve(error.errMsg?.includes('cancel') ? 'cancelled' : 'unknown'),
      });
    } catch {
      resolve('unknown');
    }
  });
}

/** Coordinates only original resident orders; every authority decision remains server-side. */
export class PaymentController {
  private epoch = 0;
  private busy = false;
  private off = onContextReset(() => this.pause());
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
  private async run<T>(operation: (epoch: number) => Promise<T>): Promise<T> {
    if (this.busy) throw new Error('正在核实原支付，请稍候');
    this.busy = true;
    const epoch = this.epoch;
    try {
      if (!authenticatedUserId()) await restoreSession();
      this.current(epoch);
      return await operation(epoch);
    } finally {
      if (epoch === this.epoch) this.busy = false;
    }
  }
  private async restore(
    billId: string,
    value: PendingPayment,
    epoch: number,
  ): Promise<PaymentOrder> {
    if (value.orderId) {
      const result = await api.order(value.orderId);
      this.current(epoch);
      return reconcilePaymentOrder(result);
    }
    const previous = await api.orders(1, '', {
      idempotency_key: value.key,
      page_size: 1,
    });
    this.current(epoch);
    // An empty lookup is never permission to rotate the original key.
    let result: PaymentOrder;
    try {
      result =
        previous.items[0] || (await api.createOrder(value.data, value.key));
    } catch (error) {
      this.current(epoch);
      if (
        error instanceof ApiError &&
        ['payment.bill_version_conflict', 'payment.bill_not_payable'].includes(
          error.code,
        )
      )
        remove(scopedKey('bill', billId));
      throw error;
    }
    this.current(epoch);
    remember(billId, { ...value, orderId: result.id });
    const current = await api.order(result.id);
    this.current(epoch);
    return reconcilePaymentOrder(current);
  }

  recover(billId: string): Promise<PaymentOrder | null> {
    return this.run(async (epoch) => {
      const value = readPending(billId);
      return value ? this.restore(billId, value, epoch) : null;
    });
  }
  create(bill: ResidentBill): Promise<PaymentOrder> {
    return this.run(async (epoch) => {
      // Recovery must run before current house authorization or bill validity checks.
      const previous = readPending(bill.id);
      if (previous) return this.restore(bill.id, previous, epoch);
      if (bill.own_payment_order_id) {
        const result = await api.order(bill.own_payment_order_id);
        this.current(epoch);
        return reconcilePaymentOrder(result);
      }
      const current = await api.bill(bill.id);
      this.current(epoch);
      if (
        current.row_version !== bill.row_version ||
        current.outstanding_cents !== bill.outstanding_cents
      )
        throw new ApiError(
          409,
          'payment.bill_version_conflict',
          '账单金额或状态已变化，请重新核对后支付',
        );
      if (current.own_payment_order_id) {
        const result = await api.order(current.own_payment_order_id);
        this.current(epoch);
        return reconcilePaymentOrder(result);
      }
      if (current.payment_availability !== 'available')
        throw new ApiError(
          409,
          'payment.bill_not_payable',
          '此账单当前无法支付，请刷新查看原因',
        );
      const value: PendingPayment = {
        key: newKey(),
        data: {
          items: [{ bill_id: bill.id, expected_row_version: bill.row_version }],
        },
      };
      remember(bill.id, value);
      try {
        return await this.restore(bill.id, value, epoch);
      } catch (error) {
        this.current(epoch);
        if (
          error instanceof ApiError &&
          [
            'payment.bill_version_conflict',
            'payment.bill_not_payable',
          ].includes(error.code)
        )
          remove(scopedKey('bill', bill.id));
        throw error;
      }
    });
  }

  pay(item: PaymentOrder): Promise<{ order: PaymentOrder; message: string }> {
    return this.run(async (epoch) => {
      let current = await api.order(item.id);
      this.current(epoch);
      reconcilePaymentOrder(current);
      if (!canContinuePayment(current))
        return {
          order: current,
          message: hasUncertainPayment(current)
            ? '结果确认中，请勿重复付款'
            : '',
        };
      const parameters = await api.parameters(item.id);
      this.current(epoch);
      if (
        parameters.payment_order_id !== item.id ||
        parameters.channel !== 'wechat_pay'
      )
        throw new ApiError(
          502,
          'payment.invalid_parameters',
          '支付参数尚未就绪，请核实原订单',
        );
      // Another page may have opened the same panel while parameters were in flight.
      if (!canContinuePayment(current))
        return { order: current, message: '结果确认中，请勿重复付款' };
      save(scopedKey('uncertain', item.id), true);
      const panel = await requestPayment(parameters.client_parameters);
      this.current(epoch);
      if (panel === 'cancelled') remove(scopedKey('uncertain', item.id));
      try {
        await api.refresh(item.id);
        this.current(epoch);
        current = await api.order(item.id);
        this.current(epoch);
        reconcilePaymentOrder(current);
      } catch (error) {
        this.current(epoch);
        if (!isUnknownResult(error)) throw error;
      }
      return {
        order: current,
        message: terminal(current)
          ? ''
          : panel === 'cancelled'
            ? '已取消本次支付面板，原订单保留，可继续或核实结果'
            : '结果确认中，请勿重复付款',
      };
    });
  }
  refresh(item: PaymentOrder): Promise<PaymentOrder> {
    return this.run(async (epoch) => {
      const current = await api.order(item.id);
      this.current(epoch);
      if (!current.available_actions.some((action) => action === 'refresh'))
        return reconcilePaymentOrder(current);
      const result = await api.refresh(item.id);
      this.current(epoch);
      return reconcilePaymentOrder(result);
    });
  }
  close(item: PaymentOrder): Promise<PaymentOrder> {
    return this.run(async (epoch) => {
      const current = await api.order(item.id);
      this.current(epoch);
      if (!current.available_actions.some((action) => action === 'close'))
        return reconcilePaymentOrder(current);
      // A lost closure response cannot safely be interpreted as permission to pay.
      save(scopedKey('uncertain', item.id), true);
      const result = await api.close(item.id);
      this.current(epoch);
      return reconcilePaymentOrder(result);
    });
  }
}
