import { API_BASE_URL, API_STORAGE_MIGRATIONS } from '../../config';
import { authenticatedUserId } from '../../core/session';
import { ApiError } from '../../core/request';

type Kind = 'resident-house' | 'resident-payment';
function keys(kind: Kind, suffix = ''): string[] {
  const owner = authenticatedUserId();
  if (!owner)
    throw new ApiError(401, 'auth.unauthenticated', '请先恢复微信登录后继续');
  return [
    ...new Set([
      API_BASE_URL,
      ...API_STORAGE_MIGRATIONS.filter((item) => item.to === API_BASE_URL).map(
        (item) => item.from,
      ),
    ]),
  ].map((base) => 'ezcmty:' + base + ':' + kind + ':' + owner + suffix);
}
const exists = (value: unknown) =>
  value !== undefined && value !== null && value !== '';
export function readStored<T>(
  kind: Kind,
  suffix: string,
  normalize: (value: unknown) => T | undefined,
): T | null {
  const [current, ...legacy] = keys(kind, suffix);
  let selected: T | undefined;
  for (const key of [current, ...legacy]) {
    const raw: unknown = wx.getStorageSync(key);
    if (!exists(raw)) continue;
    const value = normalize(raw);
    if (value === undefined)
      throw new ApiError(
        0,
        'storage.invalid',
        '原恢复资料异常，请先核实原记录',
      );
    if (
      selected !== undefined &&
      JSON.stringify(selected) !== JSON.stringify(value)
    )
      throw new ApiError(
        0,
        'storage.conflict',
        '存在不同的原恢复记录，请先核实原单',
      );
    selected = value;
    if (key !== current) {
      try {
        wx.setStorageSync(current, value);
        if (
          JSON.stringify(normalize(wx.getStorageSync(current))) !==
          JSON.stringify(value)
        )
          throw new Error();
        wx.removeStorageSync(key);
      } catch {
        throw new ApiError(
          0,
          'storage.unavailable',
          '原恢复资料尚未迁移成功，请重试或核实原单',
        );
      }
    }
  }
  return selected ?? null;
}
export function writeStored(kind: Kind, suffix: string, value: unknown): void {
  try {
    wx.setStorageSync(keys(kind, suffix)[0], value);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(
      0,
      'storage.unavailable',
      '无法保存原恢复资料，请检查设备存储后重试',
    );
  }
}
export function removeStored(kind: Kind, suffix: string): void {
  keys(kind, suffix).forEach((key) => wx.removeStorageSync(key));
}
