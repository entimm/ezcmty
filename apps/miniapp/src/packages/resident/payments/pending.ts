import { currentCredential, onSessionReset } from '../../../auth/resident';
import { API_BASE_URL } from '../../../config';
import { newKey } from '../../../shared/wechat/ui';
import { PaymentInput } from './types';
interface Pending {
  key: string;
  data: PaymentInput;
  orderId?: string;
}
let owner = currentCredential()?.userId;
const prefix = 'xlife:' + API_BASE_URL + ':payment:';
onSessionReset(() => {
  if (owner) {
    const keys = wx
      .getStorageInfoSync()
      .keys.filter((key) => key.startsWith(prefix + owner + ':'));
    keys.forEach((key) => wx.removeStorageSync(key));
  }
  owner = undefined;
});
function storageKey(billId: string): string {
  owner = currentCredential()?.userId;
  if (!owner) throw new Error('请先登录');
  const key = prefix + owner + ':' + billId;
  return key;
}
export function pending(billId: string, rowVersion: number): Pending {
  const key = storageKey(billId);
  const saved = wx.getStorageSync(key) as Pending | undefined;
  if (
    saved?.key &&
    saved.data?.items?.[0]?.bill_id === billId &&
    Number.isSafeInteger(saved.data.items[0].expected_row_version)
  )
    return saved;
  const value: Pending = {
    key: newKey(),
    data: { items: [{ bill_id: billId, expected_row_version: rowVersion }] },
  };
  wx.setStorageSync(key, value);
  return value;
}
export function rememberOrder(
  billId: string,
  value: Pending,
  orderId: string,
): void {
  wx.setStorageSync(storageKey(billId), { ...value, orderId });
}
export function clearPending(billId: string, orderId?: string): void {
  const key = storageKey(billId);
  const value = wx.getStorageSync(key) as Pending | undefined;
  if (orderId && value?.orderId !== orderId) return;
  wx.removeStorageSync(key);
}
