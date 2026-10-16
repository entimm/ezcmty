import { errorText } from '../http/client';

export const residentHome = '/packages/resident/pages/home/index';
export const claimPage = '/packages/resident/pages/claim/index';
export function safeReturn(value?: string): string {
  if (!value) return residentHome;
  let decoded: string;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    return residentHome;
  }
  return /^\/(?:packages\/resident\/pages\/(?:home|houses|claims|profile|claim|claim-detail|house-detail)|pages\/phones)\/index(?:\?(?:id|house_id|community_id)=[0-9a-f-]{36}(?:&(?:house_id|community_id)=[0-9a-f-]{36})?)?$/.test(
    decoded,
  )
    ? decoded
    : residentHome;
}
export function newKey(): string {
  // Not an authentication token; just a stable per-operation retry identifier.
  return (
    'mini_' +
    Date.now().toString(36) +
    '_' +
    Math.random().toString(36).slice(2, 12)
  );
}
export const maskPhone = (phone: string) =>
  phone.slice(0, 3) + ' ···· ' + phone.slice(-4);
export function formatTime(value: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  const pad = (v: number) => String(v).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
export function toastError(error: unknown): void {
  const message = errorText(error);
  if (message) wx.showToast({ title: message, icon: 'none', duration: 2600 });
}
export const confirm = (title: string, content: string): Promise<boolean> =>
  new Promise((resolve) =>
    wx.showModal({
      title,
      content,
      confirmColor: '#2563eb',
      success(result) {
        resolve(result.confirm);
      },
      fail() {
        resolve(false);
      },
    }),
  );
