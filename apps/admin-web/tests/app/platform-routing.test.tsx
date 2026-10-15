import { fireEvent, screen, waitFor } from '@testing-library/react';
import { vi, describe, expect, it, afterEach, beforeEach } from 'vitest';
import { safeReturnTarget } from '@/app/admin-routes';
import { mockApi, renderRoutes, companyId } from './platform-harness';

beforeEach(() => mockApi());
afterEach(() => vi.unstubAllGlobals());

describe('platform-routing', () => {
  it.each([
    ['platform.xlife.test', '平台管理 · 登录', '/api/platform/'],
    ['property.xlife.test', '物业管理 · 登录', '/api/property/'],
  ])('opens only its own login from %s root', async (host, title, apiBase) => {
    const fetcher = mockApi(null, null);
    renderRoutes('/', host);
    expect(await screen.findByText(title)).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/login?return_to=%2F',
    );
    expect(screen.queryByText('进入平台管理端')).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.every(([url]) =>
        new URL(String(url)).pathname.startsWith(apiBase),
      ),
    ).toBe(true);
  });

  it.each([
    ['platform.xlife.test', '平台管理首页', '/api/platform/'],
    ['property.xlife.test', '物业工作台', '/api/property/'],
  ])(
    'keeps %s menus, shortcuts and requests in its scope',
    async (host, title, apiBase) => {
      const fetcher = mockApi();
      renderRoutes('/', host);
      expect(await screen.findByText(title)).toBeInTheDocument();
      for (const link of screen.getAllByRole('link')) {
        expect(link.getAttribute('href')).not.toMatch(
          /^\/(platform|property)(\/|$)/,
        );
      }
      fireEvent.click(screen.getAllByRole('link', { name: '个人资料' })[0]);
      expect(await screen.findByLabelText('显示名称')).toBeInTheDocument();
      expect(screen.getByTestId('location')).toHaveTextContent('/profile');
      expect(
        fetcher.mock.calls.every(([url]) =>
          new URL(String(url)).pathname.startsWith(apiBase),
        ),
      ).toBe(true);
    },
  );

  it('normalizes old return targets and company detail links', async () => {
    renderRoutes(
      '/login?return_to=' +
        encodeURIComponent(
          `/platform/property/companies/${companyId}?admins_page=2`,
        ),
      'platform.xlife.test',
    );
    expect(
      await screen.findByRole('link', { name: '返回公司列表' }),
    ).toHaveAttribute('href', '/companies');
    expect(screen.getByTestId('location')).toHaveTextContent(
      `/companies/${companyId}?admins_page=2`,
    );
    fireEvent.click(screen.getByRole('link', { name: '返回公司列表' }));
    expect(await screen.findByRole('link', { name: '详情' })).toHaveAttribute(
      'href',
      `/companies/${companyId}`,
    );
  });

  it.each([
    ['platform.xlife.test', '/property/login', '/api/property/'],
    ['property.xlife.test', '/platform/login', '/api/platform/'],
    ['property.xlife.test', '/companies', '/api/platform/'],
    ['property.xlife.test', '/system/accounts', '/api/platform/'],
  ])('rejects client navigation to %s %s', async (host, path, foreignApi) => {
    const fetcher = mockApi();
    renderRoutes(path, host);
    await waitFor(() =>
      expect(screen.getByText('页面不存在')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('location')).toHaveTextContent(path);
    expect(
      fetcher.mock.calls.every(
        ([url]) => !new URL(String(url)).pathname.startsWith(foreignApi),
      ),
    ).toBe(true);
  });

  it('shows both portal entry points and keeps each layout independent', async () => {
    renderRoutes('/');
    fireEvent.click(screen.getByRole('link', { name: '进入平台管理端' }));
    expect(await screen.findByText('平台管理首页')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: '返回入口' }));
    fireEvent.click(screen.getByRole('link', { name: '进入物业管理端' }));
    expect(await screen.findByText('物业工作台')).toBeInTheDocument();
    expect(screen.queryByText('平台管理首页')).not.toBeInTheDocument();
  });

  it.each(['/missing', '/platform/missing/deep', '/property/missing/deep'])(
    'shows 404 for %s',
    async (path) => {
      renderRoutes(path);
      await waitFor(() =>
        expect(screen.getByText('页面不存在')).toBeInTheDocument(),
      );
    },
  );

  it('treats an invalid dynamic company identifier as an unknown route', async () => {
    const fetcher = mockApi();
    renderRoutes('/platform/property/companies/not-a-uuid');
    await waitFor(() =>
      expect(screen.getByText('页面不存在')).toBeInTheDocument(),
    );
    expect(
      fetcher.mock.calls.some(([url]) =>
        String(url).includes('/property-companies'),
      ),
    ).toBe(false);
    expect(
      safeReturnTarget(
        'platform_admin',
        `/platform/property/companies/${companyId}?admins_page=2`,
      ),
    ).toBe(`/platform/property/companies/${companyId}?admins_page=2`);
    expect(
      safeReturnTarget(
        'platform_admin',
        '/platform/property/companies/not-a-uuid',
      ),
    ).toBe('/platform');
  });
});
