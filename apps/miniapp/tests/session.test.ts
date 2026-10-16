import { beforeEach, describe, expect, it, vi } from 'vitest';
interface Pending {
  success: (result: object) => void;
  fail: () => void;
  complete: () => void;
}
const pending: Pending[] = [];
const values = new Map<string, unknown>();
const abort = vi.fn();
const key = 'xlife:http://127.0.0.1:8003:resident-session';
beforeEach(() => {
  vi.resetModules();
  pending.length = 0;
  values.clear();
  abort.mockClear();
  values.set(key, {
    token: 'resident-token',
    userId: 'user-a',
    expiresAt: '2030-01-01T00:00:00Z',
  });
  vi.stubGlobal('wx', {
    getStorageSync: (key: string) => values.get(key),
    removeStorageSync: (key: string) => values.delete(key),
    setStorageSync: (key: string, value: unknown) => values.set(key, value),
    request: (options: Pending) => {
      pending.push(options);
      return { abort };
    },
  });
});
function respond(statusCode: number, data: object) {
  const item = pending.shift()!;
  item.success({ statusCode, data });
  item.complete();
}
describe('resident session isolation', () => {
  it('drops a late success after logout even if transport ignores cancellation', async () => {
    const auth = await import('../src/auth/resident');
    const reset = vi.fn();
    auth.onSessionReset(reset);
    const old = auth.residentRequest('/miniapp-users/me');
    const { StaleSessionError } = await import('../src/shared/http/client');
    const assertion = expect(old).rejects.toBeInstanceOf(StaleSessionError);
    auth.clearSession();
    respond(200, { applicant_phone: '13800138000' });
    await assertion;
    expect(reset).toHaveBeenCalledOnce();
    expect(abort).toHaveBeenCalledOnce();
    expect(values.size).toBe(0);
  });
  it.each([0, 503])(
    'keeps the session on dependency/network error %i',
    async (status) => {
      const auth = await import('../src/auth/resident');
      const call = auth.restoreSession();
      const assertion = expect(call).rejects.toBeInstanceOf(Error);
      if (status === 0) pending.shift()!.fail();
      else respond(status, { code: 'system.dependency_unavailable' });
      await assertion;
      expect(auth.currentCredential()?.token).toBe('resident-token');
    },
  );
  it('clears a revoked session on 401', async () => {
    const auth = await import('../src/auth/resident');
    const call = auth.restoreSession();
    const assertion = expect(call).rejects.toHaveProperty('status', 401);
    respond(401, { code: 'auth.unauthenticated' });
    await assertion;
    expect(auth.currentCredential()).toBeNull();
    expect(values.size).toBe(0);
  });
  it('stores only credentials and identity after WeChat login', async () => {
    const auth = await import('../src/auth/resident');
    auth.clearSession();
    Object.assign(wx, {
      login: (options: { success: (result: { code: string }) => void }) =>
        options.success({ code: 'wechat-once' }),
    });
    const call = auth.login();
    await Promise.resolve();
    respond(201, {
      token: 'new-token',
      expires_at: '2030-01-01T00:00:00Z',
      user: { id: 'new-user', phone: 'not-persisted' },
    });
    await call;
    expect(values.get(key)).toEqual({
      token: 'new-token',
      userId: 'new-user',
      expiresAt: '2030-01-01T00:00:00Z',
    });
  });
});
