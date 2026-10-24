export { newKey } from './ids';

export function money(cents: number): string {
  if (!Number.isSafeInteger(cents)) return '—';
  const value = Math.abs(cents);
  return (
    (cents < 0 ? '-' : '') +
    Math.floor(value / 100) +
    '.' +
    String(value % 100).padStart(2, '0')
  );
}
export function maskPhone(value: string): string {
  return value.length >= 7
    ? value.slice(0, 3) + ' **** ' + value.slice(-4)
    : '未绑定手机号';
}
export function normalizePhone(value: string): string | null {
  const phone = value.trim().replace(/^(?:\+86|0086)/, '');
  return /^1[3-9][0-9]{9}$/.test(phone) ? phone : null;
}
export function formatTime(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '—';
  // API timestamps are UTC; residents read China standard time consistently.
  const local = new Date(date.getTime() + 8 * 60 * 60 * 1000);
  const pad = (part: number) => String(part).padStart(2, '0');
  return `${local.getUTCFullYear()}-${pad(local.getUTCMonth() + 1)}-${pad(local.getUTCDate())} ${pad(local.getUTCHours())}:${pad(local.getUTCMinutes())}`;
}
