import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API_BASE_URL } from '../../src/config';
import { device } from './harness';

type RequestCall = {
  url: string;
  header: Record<string, string>;
  success: (response: {
    statusCode: number;
    data: unknown;
    header: Record<string, string>;
  }) => void;
  fail: (error: unknown) => void;
  complete: () => void;
};

beforeEach(() => {
  vi.resetModules();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('client request lifecycle', () => {
  it('drops a late response after logout and aborts the old request', async () => {
    const { wx } = device();
    let call!: RequestCall;
    const abort = vi.fn();
    wx.request.mockImplementation((options: RequestCall) => {
      call = options;
      return { abort };
    });
    const session = await import('../../src/core/session');
    const request = session.clientRequest('/miniapp-users/me');
    session.clearSession();
    call.success({
      statusCode: 200,
      data: { private: 'old-user' },
      header: {},
    });
    call.complete();
    await expect(request).rejects.toMatchObject({ name: 'StaleSessionError' });
    expect(abort).toHaveBeenCalledOnce();
    expect(session.currentCredential()).toBeNull();
  });

  it('clears credentials on 401 but retains them on a network failure', async () => {
    const { wx } = device();
    wx.request.mockImplementation((options: RequestCall) => {
      options.fail({ errMsg: 'https://secret.invalid?token=do-not-display' });
      options.complete();
      return { abort: vi.fn() };
    });
    const session = await import('../../src/core/session');
    const { errorText } = await import('../../src/core/request');
    let failure: unknown;
    try {
      await session.clientRequest('/miniapp-users/me');
    } catch (error) {
      failure = error;
    }
    expect(errorText(failure)).toBe('网络连接失败，请检查网络后重试');
    expect(session.currentCredential()?.userId).toBe('resident-a');
    wx.request.mockImplementation((options: RequestCall) => {
      options.success({
        statusCode: 401,
        data: { code: 'auth.unauthenticated' },
        header: {},
      });
      options.complete();
      return { abort: vi.fn() };
    });
    await expect(
      session.clientRequest('/miniapp-users/me'),
    ).rejects.toMatchObject({ status: 401 });
    expect(session.currentCredential()).toBeNull();
  });

  it('does not install a late login after the user has cleared the session', async () => {
    const { wx } = device();
    let finish!: (value: { code: string }) => void;
    wx.login.mockImplementation((options: { success: typeof finish }) => {
      finish = options.success;
    });
    const session = await import('../../src/core/session');
    const pending = session.login();
    session.clearSession();
    finish({ code: 'one-use-code' });
    await expect(pending).rejects.toMatchObject({ name: 'StaleSessionError' });
    expect(wx.request).not.toHaveBeenCalled();
    expect(session.currentCredential()).toBeNull();
  });

  it('keeps the client token on the client audience and returns only allowed native pages', async () => {
    const { wx } = device();
    let call!: RequestCall;
    wx.request.mockImplementation((options: RequestCall) => {
      call = options;
      options.success({ statusCode: 200, data: {}, header: {} });
      options.complete();
      return { abort: vi.fn() };
    });
    const session = await import('../../src/core/session');
    await session.clientRequest('/miniapp-users/me');
    expect(call.url).toBe(
      API_BASE_URL.replace(/\/$/, '') + '/v1/miniapp-users/me',
    );
    expect(call.header.Authorization).toBe('Bearer test-token');
    expect(session.safeReturn('/pages/phones/index')).toBe(
      '/pages/phones/index',
    );
    expect(session.safeReturn('https://external.invalid')).toBe(
      '/packages/resident/pages/home/index',
    );
    expect(session.safeReturn('/packages/property/pages/approval/index')).toBe(
      '/packages/resident/pages/home/index',
    );
  });

  it('presents rate limiting with its retry delay without native diagnostics', async () => {
    const { wx } = device();
    wx.request.mockImplementation((options: RequestCall) => {
      options.success({
        statusCode: 429,
        data: { code: 'rate.limited' },
        header: { 'Retry-After': '12' },
      });
      options.complete();
      return { abort: vi.fn() };
    });
    const { clientRequest } = await import('../../src/core/session');
    const { errorText } = await import('../../src/core/request');
    try {
      await clientRequest('/miniapp-users/me');
    } catch (error) {
      expect(errorText(error)).toBe('操作较频繁，请 12 秒后重试');
    }
  });
});

it('never treats the old resident credential as a client credential', async () => {
  const { storage } = device();
  const prefix = 'ezcmty:' + API_BASE_URL;
  storage.delete(prefix + ':client-session');
  storage.set(prefix + ':resident-session', {
    token: 'old-resident-token',
    userId: 'resident-a',
    expiresAt: '2030-01-01T00:00:00Z',
  });
  const session = await import('../../src/core/session');
  expect(session.currentCredential()).toBeNull();
  await expect(
    session.clientRequest('/miniapp-users/me'),
  ).rejects.toMatchObject({ status: 401 });
  expect(storage.has(prefix + ':client-session')).toBe(false);
});
it.each(['resident-a', 'resident-b'])(
  'does not let an old completed restore replace a fresh token for %s',
  async (userId) => {
    const { wx } = device();
    const calls: RequestCall[] = [];
    wx.request.mockImplementation((call: RequestCall) => {
      calls.push(call);
      return { abort: vi.fn() };
    });
    wx.login.mockImplementation(
      (options: { success(result: { code: string }): void }) =>
        options.success({ code: 'fresh-code' }),
    );
    const session = await import('../../src/core/session');
    const restoring = session.restoreSession();
    const signing = session.login();
    const results = Promise.allSettled([restoring, signing]);
    await Promise.resolve();
    calls[0].success({
      statusCode: 200,
      data: {
        user: { id: 'resident-a', enabled: true },
        expires_at: '2028-01-01T00:00:00Z',
      },
      header: {},
    });
    calls[0].complete();
    calls[1].success({
      statusCode: 201,
      data: {
        token: 'fresh-token',
        user: { id: userId, enabled: true },
        expires_at: '2031-01-01T00:00:00Z',
      },
      header: {},
    });
    calls[1].complete();
    expect(await results).toMatchObject([
      { status: 'rejected', reason: { name: 'StaleSessionError' } },
      { status: 'fulfilled' },
    ]);
    expect(session.currentCredential()).toEqual({
      token: 'fresh-token',
      userId,
      expiresAt: '2031-01-01T00:00:00Z',
    });
  },
);
it('ignores an old token 401 after a same-user token replacement', async () => {
  const { wx } = device();
  const calls: RequestCall[] = [];
  wx.request.mockImplementation((call: RequestCall) => {
    calls.push(call);
    return { abort: vi.fn() };
  });
  wx.login.mockImplementation(
    (options: { success(result: { code: string }): void }) =>
      options.success({ code: 'new-code' }),
  );
  const session = await import('../../src/core/session');
  const old = session.clientRequest('/miniapp-users/me');
  const signing = session.login();
  await Promise.resolve();
  calls[1].success({
    statusCode: 201,
    data: {
      token: 'fresh-token',
      user: { id: 'resident-a', enabled: true },
      expires_at: '2031-01-01T00:00:00Z',
    },
    header: {},
  });
  calls[1].complete();
  await signing;
  calls[0].success({
    statusCode: 401,
    data: { code: 'auth.unauthenticated' },
    header: {},
  });
  calls[0].complete();
  await expect(old).rejects.toMatchObject({ name: 'StaleSessionError' });
  expect(session.currentCredential()?.token).toBe('fresh-token');
});
