import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { vi, describe, expect, it, afterEach, beforeEach } from 'vitest';
import { mockApi, renderRoutes, session } from '../../app/platform-harness';

beforeEach(() => mockApi());
afterEach(() => vi.unstubAllGlobals());

describe('accounts', () => {
  it('shows 403 without requesting a forbidden resource', async () => {
    const fetcher = mockApi({ ...session, permissions: ['admin.role.read'] });
    renderRoutes('/platform/system/accounts');
    expect(await screen.findByText('无权访问此页面')).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([url]) =>
        String(url).includes('/admin-accounts?'),
      ),
    ).toBe(false);
  });

  it('hides write actions for a read-only account', async () => {
    mockApi({ ...session, permissions: ['admin.account.read'] });
    renderRoutes('/platform/system/accounts');
    expect(await screen.findByText('成员')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '创建管理员' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '重置密码' }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '详情' })).toBeInTheDocument();
  });

  it('loads account details on demand', async () => {
    const fetcher = mockApi();
    renderRoutes('/platform/system/accounts');
    await screen.findByText('成员');
    expect(
      fetcher.mock.calls.some(([url]) =>
        String(url).endsWith('/admin-accounts/member'),
      ),
    ).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '详情' }));
    await screen.findByText('管理员详情');
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(([url]) =>
          String(url).endsWith('/admin-accounts/member'),
        ),
      ).toBe(true),
    );
    fireEvent.click(screen.getByRole('button', { name: '关闭' }));
    await waitFor(() =>
      expect(screen.queryByText('管理员详情')).not.toBeInTheDocument(),
    );
  });

  it('sends CSRF for an account creation', async () => {
    const fetcher = mockApi();
    renderRoutes('/platform/system/accounts');
    await screen.findByText('成员');
    fireEvent.click(screen.getByRole('button', { name: '创建管理员' }));
    const drawer = within(await screen.findByRole('dialog'));
    fireEvent.change(drawer.getByLabelText('登录名'), {
      target: { value: 'new-user' },
    });
    fireEvent.change(drawer.getByLabelText('显示名称'), {
      target: { value: '新管理员' },
    });
    fireEvent.change(drawer.getByLabelText('初始密码'), {
      target: { value: 'test-new-password' },
    });
    fireEvent.change(drawer.getByLabelText('确认密码'), {
      target: { value: 'test-new-password' },
    });
    fireEvent.click(drawer.getByRole('button', { name: '保 存' }));
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith('/admin-accounts') && init?.method === 'POST',
        ),
      ).toBe(true),
    );
    const call = fetcher.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith('/admin-accounts') && init?.method === 'POST',
    )!;
    expect(new Headers(call[1]?.headers).get('X-CSRF-Token')).toBe(
      'csrf-token',
    );
    expect(JSON.parse(String(call[1]?.body))).toMatchObject({ role_ids: [] });
  });
});
