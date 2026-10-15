import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { vi, describe, expect, it, afterEach, beforeEach } from 'vitest';
import {
  mockApi,
  renderRoutes,
  companyId,
  session,
} from '../../app/platform-harness';

beforeEach(() => mockApi());
afterEach(() => vi.unstubAllGlobals());

describe('property-onboarding', () => {
  it.each([
    ['company list', '/platform/property/companies'],
    ['company detail', `/platform/property/companies/${companyId}`],
  ])(
    'shows an activation conflict without an unhandled rejection on the %s',
    async (_, route) => {
      const fetcher = mockApi();
      const fallback = fetcher.getMockImplementation()!;
      const detail = '启用公司需要至少一名有效超级管理员';
      fetcher.mockImplementation(async (url, init) => {
        const path = new URL(String(url)).pathname;
        if (
          path.endsWith(`/property-companies/${companyId}`) &&
          init?.method === 'PATCH'
        )
          return Response.json(
            {
              type: 'urn:problem:property.company_admin_required',
              title: detail,
              status: 409,
              detail,
              instance: 'urn:request:company-enable',
              code: 'property.company_admin_required',
              request_id: 'company-enable',
            },
            {
              status: 409,
              headers: { 'Content-Type': 'application/problem+json' },
            },
          );
        if (path.endsWith(`/${companyId}/admin-accounts`))
          return Response.json({ items: [], total: 0, page: 1, page_size: 20 });
        return fallback(url, init);
      });
      renderRoutes(route);
      fireEvent.click(await screen.findByRole('button', { name: '启用' }));
      const dialog = await screen.findByRole('dialog');
      const confirm = within(dialog);
      fireEvent.click(confirm.getByRole('button', { name: '确 定' }));

      expect(await screen.findByText(detail)).toBeInTheDocument();
      // jsdom 不运行 CSS 动画，在确认框开始关闭后补发过渡结束事件。
      await waitFor(() => expect(dialog).toHaveClass('ant-zoom-leave-active'));
      fireEvent.transitionEnd(dialog);
      await waitFor(() =>
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
      );
      expect(screen.getByRole('button', { name: '启用' })).toBeEnabled();
      const writes = fetcher.mock.calls.filter(
        ([, init]) => init?.method === 'PATCH',
      );
      expect(writes).toHaveLength(1);
      expect(JSON.parse(String(writes[0][1]?.body))).toEqual({ enabled: true });
      await waitFor(() =>
        expect(
          fetcher.mock.calls.filter(
            ([url, init]) =>
              new URL(String(url)).pathname.endsWith(
                route.endsWith(companyId)
                  ? `/property-companies/${companyId}`
                  : '/property-companies',
              ) && !init?.method,
          ).length,
        ).toBeGreaterThanOrEqual(2),
      );
    },
  );

  it('guards company detail and only loads independently permitted sections', async () => {
    const fetcher = mockApi({
      ...session,
      permissions: ['property.company.read'],
    });
    renderRoutes(`/platform/property/companies/${companyId}`);
    expect((await screen.findAllByText('联系人')).length).toBeGreaterThan(0);
    expect(
      screen.queryByRole('button', { name: '开通公司管理员' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '创建小区' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '编辑' }),
    ).not.toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(
        ([url]) =>
          String(url).includes('/communities?') ||
          String(url).includes(`/${companyId}/admin-accounts`),
      ),
    ).toBe(false);
  });

  it('does not load property data for a forbidden company detail route', async () => {
    const fetcher = mockApi({
      ...session,
      permissions: ['property.community.read'],
    });
    renderRoutes(`/platform/property/companies/${companyId}`);
    expect(await screen.findByText('无权访问此页面')).toBeInTheDocument();
    expect(
      fetcher.mock.calls.some(([url]) =>
        String(url).includes('/property-companies'),
      ),
    ).toBe(false);
  });

  it('provisions a company administrator with CSRF and only the onboarding fields', async () => {
    const fetcher = mockApi();
    renderRoutes(`/platform/property/companies/${companyId}`);
    fireEvent.click(
      await screen.findByRole('button', { name: '开通公司管理员' }),
    );
    const drawer = within(await screen.findByRole('dialog'));
    fireEvent.change(drawer.getByLabelText('登录名'), {
      target: { value: 'new-company-admin' },
    });
    fireEvent.change(drawer.getByLabelText('显示名称'), {
      target: { value: '新公司管理员' },
    });
    fireEvent.change(drawer.getByLabelText('初始密码'), {
      target: { value: 'test-company-password' },
    });
    fireEvent.change(drawer.getByLabelText('确认密码'), {
      target: { value: 'test-company-password' },
    });
    fireEvent.click(drawer.getByRole('button', { name: '保 存' }));
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith(`/${companyId}/admin-accounts`) &&
            init?.method === 'POST',
        ),
      ).toBe(true),
    );
    const call = fetcher.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith(`/${companyId}/admin-accounts`) &&
        init?.method === 'POST',
    )!;
    expect(new Headers(call[1]?.headers).get('X-CSRF-Token')).toBe(
      'csrf-token',
    );
    expect(JSON.parse(String(call[1]?.body))).toEqual({
      login_name: 'new-company-admin',
      display_name: '新公司管理员',
      password: 'test-company-password',
    });
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    );
    expect(
      fetcher.mock.calls.filter(
        ([url, init]) =>
          String(url).includes(`/${companyId}/admin-accounts?`) &&
          !init?.method,
      ).length,
    ).toBeGreaterThanOrEqual(2);
  });

  it('creates a community from company detail with the fixed company and refreshes its list', async () => {
    const fetcher = mockApi();
    renderRoutes(`/platform/property/companies/${companyId}`);
    fireEvent.click(await screen.findByRole('button', { name: '创建小区' }));
    const drawer = within(await screen.findByRole('dialog'));
    fireEvent.change(drawer.getByLabelText('小区编码'), {
      target: { value: 'NEW' },
    });
    fireEvent.change(drawer.getByLabelText('小区名称'), {
      target: { value: '新小区' },
    });
    fireEvent.change(drawer.getByLabelText('地址'), {
      target: { value: '新街道 1 号' },
    });
    fireEvent.click(drawer.getByRole('button', { name: '保 存' }));
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith('/communities') && init?.method === 'POST',
        ),
      ).toBe(true),
    );
    const call = fetcher.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith('/communities') && init?.method === 'POST',
    )!;
    expect(JSON.parse(String(call[1]?.body))).toEqual({
      property_company_id: companyId,
      code: 'NEW',
      name: '新小区',
      address: '新街道 1 号',
    });
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    );
  });

  it('restores independent URL filters and pagination for company sections', async () => {
    const fetcher = mockApi();
    renderRoutes(
      `/platform/property/companies/${companyId}?communities_page=2&communities_page_size=10&communities_name=社区&admins_page=3&admins_login_name=manager`,
    );
    await screen.findByText('公司管理人员');
    const urls = fetcher.mock.calls.map(([url]) => new URL(String(url)));
    const communityQuery = urls.find((url) =>
      url.pathname.endsWith('/communities'),
    )!;
    const adminQuery = urls.find((url) =>
      url.pathname.endsWith(`/${companyId}/admin-accounts`),
    )!;
    expect(communityQuery.searchParams.get('page')).toBe('2');
    expect(communityQuery.searchParams.get('name')).toBe('社区');
    expect(communityQuery.searchParams.get('property_company_id')).toBe(
      companyId,
    );
    expect(adminQuery.searchParams.get('page')).toBe('3');
    expect(adminQuery.searchParams.get('login_name')).toBe('manager');
  });
});
