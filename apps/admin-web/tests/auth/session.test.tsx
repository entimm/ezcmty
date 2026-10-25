import '@testing-library/jest-dom/vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, useQueryClient } from '@tanstack/react-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SessionProvider, useSession } from '../../src/auth/session';
import type { Scope, SessionResponse } from '../../src/shared/types';

afterEach(() => vi.unstubAllGlobals());
const platformSession: SessionResponse = {
  scope: 'platform_admin',
  subject_id: '00000000-0000-4000-8000-000000000001',
  login_name: 'admin',
  display_name: '平台管理员',
  permissions: ['platform.system.read', 'property.company.read'],
  must_change_password: false,
  csrf_token: 'csrf-platform',
};
const propertySession: SessionResponse = {
  ...platformSession,
  scope: 'property_admin',
  subject_id: '00000000-0000-4000-8000-000000000002',
  display_name: '物业管理员',
  permissions: ['property.company.read'],
  csrf_token: 'csrf-property',
};
function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
function unauthenticated() {
  return new Response(
    JSON.stringify({
      type: 'https://errors.example/unauthenticated',
      title: '请重新登录',
      status: 401,
      detail: '登录状态已失效',
      code: 'auth.unauthenticated',
      request_id: 'request-401',
    }),
    { status: 401, headers: { 'Content-Type': 'application/problem+json' } },
  );
}
function show(scope: Scope = 'platform') {
  let auth!: ReturnType<typeof useSession>, cache!: QueryClient;
  function Capture() {
    auth = useSession();
    cache = useQueryClient();
    return (
      <>
        <div data-testid="status">{auth.status}</div>
        {auth.status === 'authenticated' && (
          <div>{auth.session?.displayName}</div>
        )}
      </>
    );
  }
  const result = render(
    <SessionProvider scope={scope}>
      <Capture />
    </SessionProvider>,
  );
  return { ...result, auth: () => auth, cache: () => cache };
}
async function restored(view: ReturnType<typeof show>) {
  await waitFor(() => expect(view.auth().status).toBe('authenticated'));
}

describe('独立后台 SessionProvider', () => {
  it('从本端当前会话接口恢复身份，映射权限且不持久化凭据', async () => {
    const fetch = vi.fn().mockResolvedValue(json(platformSession));
    vi.stubGlobal('fetch', fetch);
    const view = show();
    expect(screen.getByTestId('status')).toHaveTextContent('loading');
    await restored(view);
    expect(screen.getByText('平台管理员')).toBeInTheDocument();
    expect(view.auth().session).toMatchObject({
      subjectId: platformSession.subject_id,
      permissions: platformSession.permissions,
      csrfToken: 'csrf-platform',
    });
    expect(new URL(String(fetch.mock.calls[0][0])).pathname).toBe(
      '/api/platform/v1/admin-sessions/current',
    );
    expect(fetch.mock.calls[0][1].cache).toBe('no-store');
    expect(localStorage.getItem('csrf-platform')).toBeNull();
  });
  it('恢复网络失败保持错误状态，重试成功前不进入后台', async () => {
    const fetch = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('网络中断'))
      .mockResolvedValueOnce(json(platformSession));
    vi.stubGlobal('fetch', fetch);
    const view = show();
    await waitFor(() => expect(view.auth().status).toBe('error'));
    expect(view.auth().session).toBeNull();
    expect(screen.queryByText('平台管理员')).not.toBeInTheDocument();
    await act(async () => view.auth().refreshSession());
    await restored(view);
  });
  it('已有身份重新核实网络失败时隐藏受保护内容', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(platformSession))
      .mockRejectedValueOnce(new TypeError('网络中断'));
    vi.stubGlobal('fetch', fetch);
    const view = show();
    await restored(view);
    await act(async () => view.auth().refreshSession());
    expect(view.auth().status).toBe('error');
    expect(screen.queryByText('平台管理员')).not.toBeInTheDocument();
  });
  it('业务接口 401 清除本端身份和查询缓存', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(platformSession))
      .mockResolvedValueOnce(unauthenticated());
    vi.stubGlobal('fetch', fetch);
    const view = show();
    await restored(view);
    view.cache().setQueryData(['protected'], { confidential: true });
    await act(async () => {
      await expect(
        view.auth().request('/v1/admin-accounts'),
      ).rejects.toMatchObject({ status: 401 });
    });
    expect(view.auth().status).toBe('anonymous');
    expect(view.auth().session).toBeNull();
    expect(view.cache().getQueryData(['protected'])).toBeUndefined();
  });
  it('同账号权限收缩时清除旧授权缓存，不依赖 CSRF 更换', async () => {
    const reduced = {
      ...platformSession,
      permissions: ['property.company.read'],
    };
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(platformSession))
      .mockResolvedValueOnce(json(reduced));
    vi.stubGlobal('fetch', fetch);
    const view = show();
    await restored(view);
    view
      .cache()
      .setQueryData(['platform', platformSession.subject_id, 'accounts'], {
        secret: '旧权限数据',
      });
    await act(async () => view.auth().refreshSession());
    expect(view.auth().session?.permissions).toEqual(['property.company.read']);
    expect(
      view
        .cache()
        .getQueryData(['platform', platformSession.subject_id, 'accounts']),
    ).toBeUndefined();
  });
  it('相同权限仅顺序变化保留有效缓存，避免无意义重载', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(platformSession))
      .mockResolvedValueOnce(
        json({
          ...platformSession,
          permissions: [...platformSession.permissions].reverse(),
        }),
      );
    vi.stubGlobal('fetch', fetch);
    const view = show();
    await restored(view);
    view.cache().setQueryData(['retained'], '有效数据');
    await act(async () => view.auth().refreshSession());
    expect(view.cache().getQueryData(['retained'])).toBe('有效数据');
  });
  it('恢复响应的后台作用域不匹配时拒绝身份', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(propertySession)));
    const view = show();
    await waitFor(() => expect(view.auth().status).toBe('error'));
    expect(view.auth().session).toBeNull();
    expect(view.auth().error).toBe('后台身份不匹配');
    expect(screen.queryByText('物业管理员')).not.toBeInTheDocument();
  });
  it('登录响应作用域不匹配时保持未登录，不接受另一后台身份', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(unauthenticated())
      .mockResolvedValueOnce(json(propertySession));
    vi.stubGlobal('fetch', fetch);
    const view = show();
    await waitFor(() => expect(view.auth().status).toBe('anonymous'));
    await act(async () => {
      await expect(
        view.auth().login('admin', 'input-password'),
      ).rejects.toThrow('后台身份不匹配');
    });
    expect(view.auth().status).toBe('anonymous');
    expect(view.auth().session).toBeNull();
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
      login_name: 'admin',
      password: 'input-password',
    });
  });
  it('退出使进行中的旧身份请求中止，晚到响应不能返回旧数据', async () => {
    let deliver!: (response: Response) => void;
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockImplementation((url, options) => {
        if (options?.method === 'DELETE')
          return Promise.resolve(new Response(null, { status: 204 }));
        if (String(url).endsWith('/v1/slow'))
          return new Promise<Response>((resolve) => {
            deliver = resolve;
          });
        return Promise.resolve(json(platformSession));
      });
    vi.stubGlobal('fetch', fetch);
    const view = show();
    await restored(view);
    const pending = view.auth().request('/v1/slow');
    const oldRequest = fetch.mock.calls.find(([url]) =>
      String(url).endsWith('/v1/slow'),
    );
    await act(async () => view.auth().logout());
    expect(view.auth().status).toBe('anonymous');
    expect(oldRequest?.[1]?.signal?.aborted).toBe(true);
    deliver(json({ secret: '旧身份数据' }));
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(view.cache().getQueryCache().getAll()).toHaveLength(0);
  });
  it('首次改密进入受限状态，改密必须发送当前密码并在成功后退出', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(
        json({ ...platformSession, must_change_password: true }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetch);
    const view = show();
    await waitFor(() => expect(view.auth().status).toBe('password_change'));
    await act(async () =>
      view.auth().changePassword('current-password', 'new-password-12!'),
    );
    expect(new URL(String(fetch.mock.calls[1][0])).pathname).toBe(
      '/api/platform/v1/admin-accounts/me/password-changes',
    );
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({
      current_password: 'current-password',
      new_password: 'new-password-12!',
    });
    expect(fetch.mock.calls[1][1].headers.get('X-CSRF-Token')).toBe(
      'csrf-platform',
    );
    expect(view.auth().status).toBe('anonymous');
    expect(view.auth().session).toBeNull();
  });
  it('同时存在的两个后台使用独立缓存，平台 401 不影响物业身份', async () => {
    const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation((url) => {
      if (String(url).endsWith('/v1/failure'))
        return Promise.resolve(unauthenticated());
      return Promise.resolve(
        json(
          String(url).includes('/api/property/')
            ? propertySession
            : platformSession,
        ),
      );
    });
    vi.stubGlobal('fetch', fetch);
    const platform = show('platform'),
      property = show('property');
    await restored(platform);
    await restored(property);
    platform.cache().setQueryData(['same-key'], '平台资料');
    property.cache().setQueryData(['same-key'], '物业资料');
    await act(async () => {
      await expect(
        platform.auth().request('/v1/failure'),
      ).rejects.toMatchObject({ status: 401 });
    });
    expect(platform.auth().status).toBe('anonymous');
    expect(property.auth().status).toBe('authenticated');
    expect(property.cache().getQueryData(['same-key'])).toBe('物业资料');
  });
});
