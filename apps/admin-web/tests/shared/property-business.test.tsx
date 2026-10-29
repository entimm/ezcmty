import { act, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from 'antd';
import { describe, expect, it, vi } from 'vitest';
import { AdminContext, type AdminContextValue } from '../../src/shared/context';
import { PropertyBusinessBoundary } from '../../src/features/property/runtime';
import {
  PropertyBusinessProvider,
  usePropertyBusiness,
  type PropertyBusinessApi,
  type PropertyBusinessRuntime,
} from '../../src/shared/property-business/runtime';
import { usePropertyQuery } from '../../src/shared/property-business/queries';
import { HousingPage } from '../../src/shared/property-business/Housing';
import type { AdminRequest } from '../../src/shared/request';

const empty = { items: [], total: 0, page: 1, page_size: 20 };
function context(
  overrides: Partial<AdminContextValue> = {},
): AdminContextValue {
  return {
    scope: 'property',
    session: { subjectId: 'user-a', permissions: ['property.housing.read'] },
    company: { id: 'company-a', name: '甲物业' },
    communityId: 'community-a',
    params: {},
    request: vi.fn(),
    can: () => true,
    go: vi.fn(),
    setDirty: vi.fn(),
    confirmLeave: vi.fn(),
    ...overrides,
  } as unknown as AdminContextValue;
}
function Probe({
  capture,
}: {
  capture: (runtime: PropertyBusinessRuntime) => void;
}) {
  const runtime = usePropertyBusiness();
  capture(runtime);
  const result = usePropertyQuery({
    queryKey: ['property-business', 'houses'],
    queryFn: () => runtime.api.houses(runtime.communityId, {}),
  });
  return <span>{result.data?.items[0]?.display_address || '加载中'}</span>;
}

describe('共享物业业务运行边界', () => {
  it('页面仅消费注入能力，无需后台会话或物业请求客户端', async () => {
    const nodes = vi.fn().mockResolvedValue(empty);
    const houses = vi.fn().mockResolvedValue(empty);
    const runtime = {
      api: { nodes, houses } as unknown as PropertyBusinessApi,
      can: (action) => action === 'housing.read',
      company: { id: 'company-a', name: '甲物业' },
      communityId: 'community-a',
      community: { id: 'community-a', name: '甲小区', enabled: true },
      queryIdentity: ['custom-entry', 'subject-a'],
      params: {},
      go: vi.fn(),
      setDirty: vi.fn(),
      confirmLeave: vi.fn(),
    } satisfies PropertyBusinessRuntime;
    render(
      <QueryClientProvider client={new QueryClient()}>
        <App>
          <PropertyBusinessProvider runtime={runtime}>
            <HousingPage />
          </PropertyBusinessProvider>
        </App>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(houses).toHaveBeenCalled());
    expect(screen.getByText('房屋档案')).toBeInTheDocument();
    expect(nodes).toHaveBeenCalledWith('community-a', expect.any(Object));
    expect(
      houses.mock.calls.every(([community]) => community === 'community-a'),
    ).toBe(true);
  });

  it.each(['company', 'account', 'permissions'] as const)(
    '%s 变化隔离查询，旧响应和旧回调不能作用于新范围',
    async (change) => {
      let resolveOld!: (value: unknown) => void;
      const oldRequest = vi.fn(
        () =>
          new Promise((resolve) => {
            resolveOld = resolve;
          }),
      ) as unknown as AdminRequest;
      const newRequest = vi.fn().mockResolvedValue({
        ...empty,
        items: [{ display_address: '新范围房屋' }],
      }) as unknown as AdminRequest;
      const first = context({ request: oldRequest });
      const second = context({
        request: newRequest,
        ...(change === 'company'
          ? {
              company: { id: 'company-b', name: '乙物业' },
              communityId: 'community-b',
            }
          : {
              session: {
                ...first.session,
                subjectId: change === 'account' ? 'user-b' : 'user-a',
                permissions: ['property.housing.read', 'property.bill.read'],
              },
            }),
      });
      const cache = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      let runtime!: PropertyBusinessRuntime;
      const show = (value: AdminContextValue) => (
        <QueryClientProvider client={cache}>
          <AdminContext.Provider value={value}>
            <PropertyBusinessBoundary>
              <Probe
                capture={(next) => {
                  runtime = next;
                }}
              />
            </PropertyBusinessBoundary>
          </AdminContext.Provider>
        </QueryClientProvider>
      );
      const rendered = render(show(first));
      await waitFor(() => expect(oldRequest).toHaveBeenCalledOnce());
      const stale = runtime;
      rendered.rerender(show(second));
      expect(await screen.findByText('新范围房屋')).toBeInTheDocument();
      await act(async () => {
        resolveOld({ ...empty, items: [{ display_address: '旧范围房屋' }] });
      });
      expect(screen.queryByText('旧范围房屋')).not.toBeInTheDocument();
      stale.setDirty(true);
      stale.go('house-detail', { house_id: 'old-house' });
      expect(first.go).not.toHaveBeenCalled();
      expect(second.go).not.toHaveBeenCalled();
      expect(second.setDirty).not.toHaveBeenCalled();
      await expect(stale.api.houses('community-a', {})).rejects.toThrow(
        '原业务范围已失效',
      );
      if (change === 'company') {
        await expect(
          runtime.api.submitBill(
            {
              action: 'create',
              companyId: 'company-a',
              communityId: 'community-a',
              body: {},
            },
            'original-key',
          ),
        ).rejects.toThrow('原账务操作公司已失效');
      }
      expect(newRequest).toHaveBeenCalledOnce();
      const keys = cache
        .getQueryCache()
        .getAll()
        .map((query) => query.queryKey);
      expect(keys).toEqual(
        expect.arrayContaining([
          expect.arrayContaining(['property', 'user-a', 'company-a']),
          expect.arrayContaining([
            'property',
            second.session.subjectId,
            second.company!.id,
          ]),
        ]),
      );
    },
  );

  it('没有可信公司上下文时不查询，不开放动作', async () => {
    const admin = context({ company: undefined });
    let runtime!: PropertyBusinessRuntime;
    render(
      <QueryClientProvider client={new QueryClient()}>
        <AdminContext.Provider value={admin}>
          <PropertyBusinessBoundary>
            <Probe
              capture={(next) => {
                runtime = next;
              }}
            />
          </PropertyBusinessBoundary>
        </AdminContext.Provider>
      </QueryClientProvider>,
    );
    expect(screen.getByText('加载中')).toBeInTheDocument();
    expect(runtime.can('housing.read')).toBe(false);
    expect(admin.request).not.toHaveBeenCalled();
  });
});
