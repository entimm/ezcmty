import * as account from './account-api';
import { API_BASE_URL } from '../config';
import { entryFor } from '../ui/business-navigation';
import { ApiError, StaleSessionError } from './request';
import {
  clientRequest,
  currentCredential,
  onSessionReset,
  requireSession,
  sessionRevision,
} from './session';
import type { ClientIdentity } from './types';

let active: ClientIdentity | null = null;
let directory: ClientIdentity[] | null = null;
let revision = 0;
let selection = 0;
let pending: { session: number; promise: Promise<ClientIdentity[]> } | null =
  null;
const requests = new Set<WechatMiniprogram.RequestTask>();
const listeners = new Set<() => void>();
const choiceKey = () =>
  'ezcmty:' + API_BASE_URL + ':client-identity:' + currentCredential()?.userId;
export const currentIdentity = () => (active ? { ...active } : null);
export function cancelIdentitySelection(): void {
  selection++;
}
export const contextRevision = () => revision;
export function onContextReset(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
export function clearContext(): void {
  active = null;
  revision++;
  selection++;
  requests.forEach((task) => {
    try {
      task.abort();
    } catch {
      /* Continue cancellation. */
    }
  });
  requests.clear();
  listeners.forEach((listener) => {
    try {
      listener();
    } catch {
      /* Continue clearing views. */
    }
  });
}
onSessionReset(() => {
  clearContext();
  directory = null;
  pending = null;
});
const incomplete = () =>
  new ApiError(
    503,
    'client.identity_directory_incomplete',
    '身份目录暂时不完整，请重新连接',
  );
export function loadIdentities(): Promise<ClientIdentity[]> {
  const session = sessionRevision();
  if (pending?.session === session) return pending.promise;
  const context = revision;
  const choice = selection;
  const operation = (async () => {
    const all: ClientIdentity[] = [];
    const ids = new Set<string>();
    let total: number | undefined;
    for (let page = 1; ; page++) {
      const result = await account.identities(page);
      if (session !== sessionRevision()) throw new StaleSessionError();
      if (
        !Number.isSafeInteger(result.total) ||
        result.total < 1 ||
        !Number.isSafeInteger(result.page_size) ||
        result.page_size < 1 ||
        result.page !== page ||
        !Array.isArray(result.items) ||
        (total !== undefined && total !== result.total)
      )
        throw incomplete();
      total = result.total;
      for (const item of result.items) {
        if (
          !item ||
          typeof item.id !== 'string' ||
          typeof item.type !== 'string' ||
          typeof item.display_name !== 'string' ||
          ids.has(item.id) ||
          (item.type === 'resident') !== (item.id === 'resident')
        )
          throw incomplete();
        ids.add(item.id);
        all.push(item);
      }
      if (all.length > total || (!result.items.length && all.length < total))
        throw incomplete();
      if (all.length === total) break;
    }
    if (all[0]?.id !== 'resident' || all[0]?.type !== 'resident')
      throw incomplete();
    directory = all;
    if (
      context === revision &&
      choice === selection &&
      active &&
      !all.some((item) => item.id === active?.id && item.type === active.type)
    )
      clearContext();
    return all;
  })();
  pending = { session, promise: operation };
  void operation
    .finally(() => {
      if (pending?.promise === operation) pending = null;
    })
    .catch(() => {});
  return operation;
}
export async function selectIdentity(
  identityId: string,
  canCommit: () => boolean = () => true,
): Promise<ClientIdentity> {
  const chosen = directory?.find((item) => item.id === identityId);
  if (!chosen || !entryFor(chosen.type))
    throw new ApiError(
      403,
      'client.identity_unsupported',
      '当前版本暂不支持此身份，请更新小程序',
    );
  const session = sessionRevision();
  const attempt = ++selection;
  let detail: ClientIdentity;
  try {
    detail = await account.identity(chosen.id);
  } catch (error) {
    if (
      !canCommit() &&
      !(
        error instanceof ApiError &&
        error.status === 401 &&
        !currentCredential()
      )
    )
      throw new StaleSessionError();
    if (
      session !== sessionRevision() &&
      !(
        error instanceof ApiError &&
        error.status === 401 &&
        !currentCredential()
      )
    )
      throw new StaleSessionError();
    if (
      attempt === selection &&
      error instanceof ApiError &&
      (error.status === 404 || error.code === 'client.identity_unavailable') &&
      active?.id === chosen.id
    )
      clearContext();
    throw error;
  }
  if (!canCommit() || session !== sessionRevision() || attempt !== selection)
    throw new StaleSessionError();
  if (detail.id !== chosen.id || detail.type !== chosen.type)
    throw incomplete();
  clearContext();
  active = { ...detail };
  try {
    wx.setStorageSync(choiceKey(), detail.id);
  } catch {
    /* Selection remains verified in memory. */
  }
  return detail;
}
export async function discoverIdentity(
  canCommit: () => boolean = () => true,
): Promise<ClientIdentity | null> {
  const session = sessionRevision();
  const all = await loadIdentities();
  if (!canCommit() || session !== sessionRevision())
    throw new StaleSessionError();
  let previous: unknown;
  try {
    previous = wx.getStorageSync(choiceKey());
  } catch {
    /* Choose from the directory. */
  }
  const choice =
    all.find((item) => item.id === previous && entryFor(item.type)) ||
    (all.length === 1 && all[0].type === 'resident' ? all[0] : null);
  if (!choice) return null;
  try {
    return await selectIdentity(choice.id, canCommit);
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.status === 404 || error.code === 'client.identity_unavailable')
    )
      return null;
    throw error;
  }
}
export async function businessRequest<T>(
  path: string,
  options: Parameters<typeof clientRequest>[1] = {},
  expectedType?: string,
): Promise<T> {
  if (!currentCredential())
    throw new ApiError(401, 'auth.unauthenticated', '请先微信登录');
  const identity = active;
  const context = revision;
  const session = sessionRevision();
  if (!identity || (expectedType && identity.type !== expectedType))
    throw new ApiError(403, 'client.identity_mismatch', '请先选择对应业务身份');
  try {
    const value = await clientRequest<T>(path, {
      ...options,
      identity: identity.id,
      register(task) {
        requests.add(task);
        return () => {
          requests.delete(task);
        };
      },
    });
    if (session !== sessionRevision() || context !== revision)
      throw new StaleSessionError();
    return value;
  } catch (error) {
    if (
      error instanceof ApiError &&
      error.status === 401 &&
      !currentCredential()
    )
      throw error;
    if (session !== sessionRevision() || context !== revision)
      throw new StaleSessionError();
    if (
      error instanceof ApiError &&
      error.code === 'client.identity_unavailable'
    ) {
      clearContext();
      wx.reLaunch({ url: '/pages/identities/index' });
    }
    throw error;
  }
}
export function requireIdentity(type: string, returnTo: string): boolean {
  if (!requireSession(returnTo)) return false;
  if (active?.type === type) return true;
  wx.reLaunch({
    url: '/pages/index/index?return_to=' + encodeURIComponent(returnTo),
  });
  return false;
}
