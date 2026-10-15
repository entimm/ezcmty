import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { mockApi, renderRoutes, session } from './platform-harness';

beforeEach(() => mockApi());
afterEach(() => vi.unstubAllGlobals());

describe('platform-auth', () => {
  it('returns to a clean protected URL after login', async () => {
    mockApi(null);
    renderRoutes('/system/accounts?page=2', 'platform.xlife.test');
    expect(await screen.findByText('平台管理 · 登录')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/login?return_to=%2Fsystem%2Faccounts%3Fpage%3D2',
    );
    fireEvent.change(screen.getByLabelText('登录名'), {
      target: { value: 'root' },
    });
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'test-login-password' },
    });
    fireEvent.click(screen.getByRole('button', { name: '登 录' }));
    expect(await screen.findByText('成员')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/system/accounts?page=2',
    );
  });

  it('uses clean paths for the forced password flow', async () => {
    mockApi({ ...session, must_change_password: true, permissions: [] });
    renderRoutes('/profile', 'platform.xlife.test');
    expect(await screen.findByText('首次登录 · 修改密码')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/change-password',
    );
  });

  it('returns to a protected deep link after login', async () => {
    const fetcher = mockApi(null);
    renderRoutes('/platform/system/accounts');
    expect(await screen.findByText('平台管理 · 登录')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('登录名'), {
      target: { value: 'root' },
    });
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'test-login-password' },
    });
    fireEvent.click(screen.getByRole('button', { name: '登 录' }));
    expect(await screen.findByText('成员')).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith('/admin-sessions') && init?.method === 'POST',
      ),
    ).toBe(true);
  });

  it('restricts the initial session to the password change page', async () => {
    const fetcher = mockApi({
      ...session,
      must_change_password: true,
      permissions: [],
    });
    renderRoutes('/platform/system/accounts');
    expect(await screen.findByText('首次登录 · 修改密码')).toBeInTheDocument();
    expect(screen.getByLabelText('当前密码')).toBeInTheDocument();
    expect(
      fetcher.mock.calls.every(
        ([url]) => !String(url).includes('/admin-accounts?'),
      ),
    ).toBe(true);
  });

  it('shows a retry state when identity restoration fails', async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError('offline'))
      .mockResolvedValue(Response.json(session));
    vi.stubGlobal('fetch', fetcher);
    renderRoutes('/platform');
    expect(
      await screen.findByText('无法确认登录状态，请重试'),
    ).toBeInTheDocument();
    expect(screen.queryByText('平台管理首页')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重 试' }));
    expect(await screen.findByText('平台管理首页')).toBeInTheDocument();
  });
});
