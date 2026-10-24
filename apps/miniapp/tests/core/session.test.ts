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

describe('resident request lifecycle', () => {
  it('drops a late response after logout and aborts the old request', async () => {
    const { wx } = device();
    let call!: RequestCall;
    const abort = vi.fn();
    wx.request.mockImplementation((options: RequestCall) => {
      call = options;
      return { abort };
    });
    const session = await import('../../src/core/session');
    const request = session.residentRequest('/miniapp-users/me');
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
      await session.residentRequest('/miniapp-users/me');
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
      session.residentRequest('/miniapp-users/me'),
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

  it('keeps the resident token on the resident audience and returns only allowed native pages', async () => {
    const { wx } = device();
    let call!: RequestCall;
    wx.request.mockImplementation((options: RequestCall) => {
      call = options;
      options.success({ statusCode: 200, data: {}, header: {} });
      options.complete();
      return { abort: vi.fn() };
    });
    const session = await import('../../src/core/session');
    await session.residentRequest('/miniapp-users/me');
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
    const { residentRequest } = await import('../../src/core/session');
    const { errorText } = await import('../../src/core/request');
    try {
      await residentRequest('/miniapp-users/me');
    } catch (error) {
      expect(errorText(error)).toBe('操作较频繁，请 12 秒后重试');
    }
  });
});
