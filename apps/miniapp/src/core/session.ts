import { API_BASE_URL } from '../config';
import { ApiError, HttpMethod, request, StaleSessionError } from './request';
import { Session, SessionState } from './types';

export interface Credential {
  token: string;
  userId: string;
  expiresAt: string;
}

const storageKey = 'ezcmty:' + API_BASE_URL + ':resident-session';
let credential: Credential | null | undefined;
let revision = 0;
let loginPromise: Promise<void> | null = null;
const requests = new Set<WechatMiniprogram.RequestTask>();
const resetListeners = new Set<() => void>();

export function currentCredential(): Credential | null {
  if (credential === undefined) {
    try {
      const stored = wx.getStorageSync(
        storageKey,
      ) as Partial<Credential> | null;
      credential =
        stored &&
        typeof stored.token === 'string' &&
        stored.token.length > 0 &&
        typeof stored.userId === 'string' &&
        stored.userId.length > 0 &&
        typeof stored.expiresAt === 'string' &&
        Number.isFinite(Date.parse(stored.expiresAt))
          ? {
              token: stored.token,
              userId: stored.userId,
              expiresAt: stored.expiresAt,
            }
          : null;
    } catch {
      credential = null;
    }
  }
  return credential;
}

export const sessionRevision = (): number => revision;

export function onSessionReset(listener: () => void): () => void {
  resetListeners.add(listener);
  return () => {
    resetListeners.delete(listener);
  };
}

export function clearSession(): void {
  revision++;
  credential = null;
  loginPromise = null;
  try {
    wx.removeStorageSync(storageKey);
  } catch {
    /* Memory is already cleared. */
  }
  requests.forEach((task) => {
    try {
      task.abort();
    } catch {
      /* Continue clearing every request. */
    }
  });
  requests.clear();
  resetListeners.forEach((listener) => {
    try {
      listener();
    } catch {
      /* One view cannot prevent other scopes from clearing. */
    }
  });
}

function saveSession(value: Session): void {
  if (!value.token || !value.user?.id || !value.user.enabled)
    throw new ApiError(403, 'resident.disabled', '当前账号暂时无法登录');
  clearSession();
  const next = {
    token: value.token,
    userId: value.user.id,
    expiresAt: value.expires_at,
  };
  try {
    wx.setStorageSync(storageKey, next);
  } catch {
    throw new ApiError(
      0,
      'storage.unavailable',
      '无法保存登录状态，请检查设备存储后重试',
    );
  }
  credential = next;
}

export async function residentRequest<T>(
  path: string,
  options: { method?: HttpMethod; data?: object; key?: string } = {},
): Promise<T> {
  const current = currentCredential();
  if (!current) throw new ApiError(401, 'auth.unauthenticated', '请先微信登录');
  const started = revision;
  try {
    const result = await request<T>(API_BASE_URL, path, {
      ...options,
      token: current.token,
      register(task) {
        requests.add(task);
        return () => {
          requests.delete(task);
        };
      },
    });
    if (started !== revision) throw new StaleSessionError();
    return result;
  } catch (error) {
    if (started !== revision) throw new StaleSessionError();
    if (error instanceof ApiError && error.status === 401) clearSession();
    throw error;
  }
}

export function login(): Promise<void> {
  if (loginPromise) return loginPromise;
  const started = revision;
  const operation = (async () => {
    const code = await new Promise<string>((resolve, reject) => {
      wx.login({
        success(result) {
          if (result.code) resolve(result.code);
          else
            reject(
              new ApiError(0, 'wechat.login_failed', '微信登录未完成，请重试'),
            );
        },
        fail() {
          reject(
            new ApiError(0, 'wechat.login_failed', '微信登录未完成，请重试'),
          );
        },
      });
    });
    if (started !== revision) throw new StaleSessionError();
    const result = await request<Session>(API_BASE_URL, '/resident-sessions', {
      method: 'POST',
      data: { code },
    });
    if (started !== revision) throw new StaleSessionError();
    saveSession(result);
  })();
  loginPromise = operation;
  void operation
    .finally(() => {
      if (loginPromise === operation) loginPromise = null;
    })
    .catch(() => {});
  return operation;
}

export async function restoreSession(): Promise<SessionState> {
  const result = await residentRequest<SessionState>(
    '/resident-sessions/current',
  );
  const current = currentCredential();
  if (!current || result.user.id !== current.userId || !result.user.enabled) {
    clearSession();
    throw new ApiError(
      401,
      'auth.unauthenticated',
      '登录已过期，请重新微信登录',
    );
  }
  credential = { ...current, expiresAt: result.expires_at };
  try {
    wx.setStorageSync(storageKey, credential);
  } catch {
    /* The active in-memory session remains valid. */
  }
  return result;
}

export async function logout(): Promise<void> {
  const started = revision;
  try {
    await residentRequest<void>('/resident-sessions/current', {
      method: 'DELETE',
    });
  } finally {
    if (started === revision) clearSession();
  }
}

export function safeReturn(value?: string): string {
  const home = '/packages/resident/pages/home/index';
  if (!value) return home;
  let decoded: string;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    return home;
  }
  return /^\/(?:packages\/resident\/pages\/(?:home|houses|claims|profile|claim|claim-detail|house-detail|bills|bill-detail|payment-confirm|payment-orders|payment-detail)|pages\/phones)\/index(?:\?(?:id|house_id|community_id)=[0-9a-f-]{36}(?:&(?:house_id|community_id)=[0-9a-f-]{36})?)?$/.test(
    decoded,
  )
    ? decoded
    : home;
}

export function requireSession(returnTo: string): boolean {
  if (currentCredential()) return true;
  wx.navigateTo({
    url:
      '/pages/login/index?return_to=' +
      encodeURIComponent(safeReturn(returnTo)),
  });
  return false;
}
