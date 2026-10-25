import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from 'antd';
import { describe, expect, it, vi } from 'vitest';
import {
  BillingBasisDialog,
  FeeBasisPanel,
} from '../../../src/features/property/BillingBasis';
import {
  AdminContext,
  type AdminContextValue,
} from '../../../src/shared/context';
import type { AdminRequest, RequestOptions } from '../../../src/shared/request';

const house = {
  id: 'house-1',
  community_id: 'community-1',
  label: '锦绣小区／1栋／101',
  enabled: true,
  effective_enabled: true,
};

function show(element: React.ReactNode, permissions: string[]) {
  const calls: { path: string; options?: RequestOptions }[] = [];
  const request = (async (path: string, options?: RequestOptions) => {
    calls.push({ path, options });
    if (path.includes('/house-options'))
      return { items: [house], total: 1, page: 1, page_size: 20 };
    if (path.includes('/property-fee-basis-versions')) {
      if (options?.method === 'POST') return { id: 'basis-new', version_no: 1 };
      return { items: [], total: 0, page: 1, page_size: 20 };
    }
    if (path.includes('/property-fee-calculation'))
      return { available: false, basis: null, receivable_cents: null };
    throw new Error(`Unexpected request: ${path}`);
  }) as AdminRequest;
  const can = (permission: string) => permissions.includes(permission);
  const context = {
    scope: 'property',
    request,
    can,
    hasPermission: can,
    communityId: house.community_id,
    params: {},
    setDirty: vi.fn(),
    confirmLeave: (next: () => void) => next(),
  } as unknown as AdminContextValue;
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <AdminContext.Provider value={context}>
        <App>{element}</App>
      </AdminContext.Provider>
    </QueryClientProvider>,
  );
  return calls;
}

describe('仅账务授权的计费依据入口', () => {
  it('账单只读人员可经最小选项查询和试算，不读取房产或业主档案', async () => {
    const calls = show(<BillingBasisDialog onClose={vi.fn()} />, [
      'property.bill.read',
    ]);
    fireEvent.click(await screen.findByRole('button', { name: '查看依据' }));
    expect(await screen.findByText('暂无适用依据')).toBeInTheDocument();
    await waitFor(() =>
      expect(
        calls.some(({ path }) => path.includes('/property-fee-calculation')),
      ).toBe(true),
    );
    expect(
      screen.queryByRole('button', { name: '新增依据版本' }),
    ).not.toBeInTheDocument();
    expect(
      calls.every(
        ({ path, options }) =>
          !path.includes('/owners') &&
          !/\/houses(?:\?|$)/.test(path) &&
          !(
            path.includes('/property-fee-basis-versions') &&
            options?.method === 'POST'
          ),
      ),
    ).toBe(true);
  });

  it('计费依据维护可独立新增版本，提交当前版本和固定金额，避免授予房产维护', async () => {
    const calls = show(
      <FeeBasisPanel house={{ ...house, display_address: house.label }} />,
      ['property.bill.read', 'property.fee_basis.manage'],
    );
    fireEvent.click(
      await screen.findByRole('button', { name: /新增依据版本/ }),
    );
    fireEvent.click(await screen.findByRole('radio', { name: '固定月费' }));
    fireEvent.change(await screen.findByLabelText('固定月费（元）'), {
      target: { value: '100' },
    });
    fireEvent.change(screen.getByLabelText('变更原因'), {
      target: { value: '按最新标准执行' },
    });
    fireEvent.click(screen.getByRole('button', { name: '确认保存' }));
    await waitFor(() =>
      expect(
        calls.filter(
          ({ path, options }) =>
            path.includes('/property-fee-basis-versions') &&
            options?.method === 'POST',
        ),
      ).toHaveLength(1),
    );
    const saved = calls.find(
      ({ path, options }) =>
        path.includes('/property-fee-basis-versions') &&
        options?.method === 'POST',
    )!;
    expect(saved.path).toContain('/houses/house-1/property-fee-basis-versions');
    expect(JSON.parse(String(saved.options?.body))).toMatchObject({
      expected_latest_version_no: 0,
      fixed_amount_cents: 10000,
      area_sqm: null,
      unit_price_cents: null,
      change_reason: '按最新标准执行',
    });
    expect(calls.every(({ path }) => !path.includes('/owners'))).toBe(true);
  });
});
