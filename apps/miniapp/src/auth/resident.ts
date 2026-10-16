import { API_BASE_URL } from '../config';
import {
  ApiError,
  HttpMethod,
  request,
  StaleSessionError,
} from '../shared/http/client';
import { PageResult, PhoneBinding, Session, SessionState } from './types';

interface Credential {
  token: string;
  userId: string;
  expiresAt: string;
}
const storageKey = 'xlife:' + API_BASE_URL + ':resident-session';
let credential: Credential | null | undefined;
let generation = 0;
const tasks = new Set<WechatMiniprogram.RequestTask>();
const listeners = new Set<() => void>();

export function currentCredential(): Credential | null {
  if (credential === undefined) {
    const saved = wx.getStorageSync(storageKey) as Partial<Credential> | null;
    credential =
      saved &&
      typeof saved.token === 'string' &&
      typeof saved.userId === 'string' &&
      typeof saved.expiresAt === 'string'
        ? {
            token: saved.token,
            userId: saved.userId,
            expiresAt: saved.expiresAt,
          }
        : null;
  }
  return credential;
}

export function onSessionReset(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function clearSession(): void {
  generation++;
  credential = null;
  wx.removeStorageSync(storageKey);
  tasks.forEach((task) => task.abort());
  tasks.clear();
  listeners.forEach((listener) => listener());
}

function saveSession(session: Session): void {
  clearSession();
  credential = {
    token: session.token,
    userId: session.user.id,
    expiresAt: session.expires_at,
  };
  wx.setStorageSync(storageKey, credential);
}

export async function residentRequest<T>(
  path: string,
  options: {
    method?: HttpMethod;
    data?: object;
    key?: string;
  } = {},
): Promise<T> {
  const session = currentCredential();
  if (!session) throw new ApiError(401, 'auth.unauthenticated', '请先微信登录');
  const started = generation;
  try {
    const result = await request<T>(API_BASE_URL, path, {
      ...options,
      token: session.token,
      register(task) {
        tasks.add(task);
        return () => tasks.delete(task);
      },
    });
    if (started !== generation) throw new StaleSessionError();
    return result;
  } catch (error) {
    if (started !== generation) throw new StaleSessionError();
    if (error instanceof ApiError && error.status === 401) clearSession();
    throw error;
  }
}

export async function login(): Promise<void> {
  const started = generation;
  const code = await new Promise<string>((resolve, reject) =>
    wx.login({
      success(result) {
        if (result.code) resolve(result.code);
        else reject(new ApiError(0, 'wechat', '微信登录失败，请重试'));
      },
      fail() {
        reject(new ApiError(0, 'wechat', '微信登录失败，请重试'));
      },
    }),
  );
  if (started !== generation) throw new StaleSessionError();
  const session = await request<Session>(API_BASE_URL, '/resident-sessions', {
    method: 'POST',
    data: { code },
  });
  if (started !== generation) throw new StaleSessionError();
  saveSession(session);
}

export const restoreSession = () =>
  residentRequest<SessionState>('/resident-sessions/current');
export async function logout(): Promise<void> {
  try {
    await residentRequest<void>('/resident-sessions/current', {
      method: 'DELETE',
    });
  } finally {
    clearSession();
  }
}
export const listPhones = (page = 1) =>
  residentRequest<PageResult<PhoneBinding>>(
    '/miniapp-users/me/phone-bindings?page_size=100&page=' + page,
  );
export const bindPhone = (code: string, key: string, expectedPhone?: string) =>
  residentRequest<PhoneBinding>('/miniapp-users/me/phone-bindings', {
    method: 'POST',
    key,
    data: { code, ...(expectedPhone ? { expected_phone: expectedPhone } : {}) },
  });
export const unbindPhone = (phone: PhoneBinding) =>
  residentRequest<void>(
    '/miniapp-users/me/phone-bindings/' +
      phone.id +
      '?expected_row_version=' +
      phone.row_version,
    { method: 'DELETE' },
  );

export function requireSession(returnTo: string): boolean {
  if (currentCredential()) return true;
  wx.navigateTo({
    url: '/pages/login/index?return_to=' + encodeURIComponent(returnTo),
  });
  return false;
}
