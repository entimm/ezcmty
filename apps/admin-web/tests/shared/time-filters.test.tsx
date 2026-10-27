import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AdminContext, type AdminContextValue } from '../../src/shared/context';
import type { AdminRequest } from '../../src/shared/request';
import {
  ClaimsPage,
  BindingsPage,
} from '../../src/features/property/Residents';
import { ImportsPage } from '../../src/shared/imports/ImportsPage';
import { createImportsApi } from '../../src/shared/imports/api';
import { PaymentOrders } from '../../src/shared/payments/PaymentOrders';
import { paymentReads } from '../../src/shared/payments/api';
import { SystemPages } from '../../src/shared/system/SystemPages';
import type { Scope } from '../../src/shared/types';
import { DatePicker } from '../../src/shared/DatePicker';
import { toPickerTime, pickerTimeToInstant } from '../../src/shared/datetime';

afterEach(() => vi.useRealTimers());

function show(
  scope: Scope,
  page: string,
  params: Record<string, string>,
  element: (context: AdminContextValue) => ReactNode,
) {
  const calls: string[] = [];
  const request = (async (path: string) => {
    calls.push(path);
    if (path.includes('permissions')) return [];
    return { items: [], total: 0, page: 1, page_size: 20 };
  }) as AdminRequest;
  const go = vi.fn();
  const context: AdminContextValue = {
    scope,
    request,
    can: () => true,
    hasPermission: () => true,
    session: {
      scope: scope === 'platform' ? 'platform_admin' : 'property_admin',
      subjectId: 'admin',
      loginName: 'admin',
      displayName: '管理员',
      permissions: [],
      mustChangePassword: false,
      csrfToken: 'csrf',
    },
    refreshSession: vi.fn().mockResolvedValue(undefined),
    communityId: 'community',
    communities: [],
    go,
    page,
    params,
    setDirty: vi.fn(),
    confirmLeave: (next) => next(),
  };
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <AdminContext.Provider value={context}>
        <App>{element(context)}</App>
      </AdminContext.Provider>
    </QueryClientProvider>,
  );
  return { calls, go };
}

describe('页面时间筛选接线', () => {
  it('手动输入夏令时缺失时段仍保留用户输入的北京时间', async () => {
    const changed = vi.fn();
    render(
      <DatePicker
        showTime
        needConfirm={false}
        defaultValue={toPickerTime('2026-03-07T18:30:00.000Z')}
        onChange={changed}
      />,
    );
    const input = screen.getByRole('textbox');
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: '2026-03-08 02:45:00' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' });
    await waitFor(() => expect(changed).toHaveBeenCalled());
    expect(pickerTimeToInstant(changed.mock.calls[0][0])).toBe(
      '2026-03-07T18:45:00.000Z',
    );
  });

  it('此刻按钮使用北京时间的日期和时分秒', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-10-31T16:30:00.000Z'));
    const changed = vi.fn();
    render(
      <ConfigProvider locale={zhCN}>
        <DatePicker showTime needConfirm={false} onChange={changed} />
      </ConfigProvider>,
    );
    fireEvent.click(screen.getByRole('textbox'));
    fireEvent.click(await screen.findByText('此刻'));
    await waitFor(() => expect(changed).toHaveBeenCalled());
    expect(changed.mock.calls[0][0].format('YYYY-MM-DD HH:mm:ss')).toBe(
      '2026-11-01 00:30:00',
    );
    expect(pickerTimeToInstant(changed.mock.calls[0][0])).toBe(
      '2026-10-31T16:30:00.000Z',
    );
  });

  it.each(['claims', 'bindings'])(
    '%s 恢复单日筛选后重提不增加一天',
    async (page) => {
      const params = {
        created_from: '2026-03-07T16:00:00.000Z',
        created_to: '2026-03-08T16:00:00.000Z',
      };
      const { calls, go } = show('property', page, params, () =>
        page === 'claims' ? <ClaimsPage /> : <BindingsPage />,
      );
      expect(screen.getAllByDisplayValue('2026-03-08')).toHaveLength(2);
      fireEvent.click(screen.getByRole('button', { name: /查\s*询/ }));
      expect(go).toHaveBeenCalledWith(page, expect.objectContaining(params));
      await waitFor(() =>
        expect(calls.some((path) => path.includes('created_from='))).toBe(true),
      );
    },
  );

  it.each([
    ['platform', 'imports'],
    ['property', 'imports'],
    ['platform', 'payments'],
    ['property', 'payments'],
  ] as const)('%s 的 %s 按上海整日区间请求服务端', async (scope, page) => {
    const params = { from: '2026-03-08', to: '2026-03-08' };
    const { calls } = show(scope, page, params, ({ request, go, setDirty }) => {
      const common = {
        scope,
        communityId: 'community',
        setDirty,
        can: () => false,
      };
      return page === 'imports' ? (
        <ImportsPage
          page={page}
          params={params}
          go={go}
          runtime={{ ...common, api: createImportsApi(request) }}
        />
      ) : (
        <PaymentOrders
          page={page}
          params={params}
          go={go}
          runtime={{
            ...common,
            api: {
              ...paymentReads(request),
              configuration: vi.fn(),
              bindings: vi.fn(),
              rules: vi.fn(),
            },
          }}
        />
      );
    });
    await waitFor(() =>
      expect(calls.some((path) => path.includes('created_before='))).toBe(true),
    );
    const path = calls.find((path) => path.includes('created_before='))!;
    const query = new URL(path, 'https://admin.example').searchParams;
    expect(query.get('created_from')).toBe('2026-03-07T16:00:00.000Z');
    expect(query.get('created_before')).toBe('2026-03-08T16:00:00.000Z');
  });

  it.each(['platform', 'property'] as const)(
    '%s 审计恢复夏令时缺失时段后保持北京时间与原查询瞬间',
    (scope) => {
      const params = {
        from_time: '2026-03-07T18:30:00.123Z',
        to_time: '2026-03-07T19:30:00.456Z',
      };
      const { go } = show(scope, 'audit', params, ({ go }) => (
        <SystemPages page="audit" params={params} go={go} />
      ));
      expect(
        screen.getByDisplayValue('2026-03-08 02:30:00'),
      ).toBeInTheDocument();
      expect(
        screen.getByDisplayValue('2026-03-08 03:30:00'),
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /查\s*询/ }));
      expect(go).toHaveBeenCalledWith('audit', expect.objectContaining(params));
    },
  );
});
