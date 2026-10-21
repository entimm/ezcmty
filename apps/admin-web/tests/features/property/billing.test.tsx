import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderRoutes } from '../../app/platform-harness';
import type { SessionResponse } from '@/shared/api/admin';
import type {
  Bill,
  BillOperation,
  BillWriteResult,
  SettlementEntry,
} from '@/features/property/billing/api';
import { pendingSnapshot, savePending } from '@/shared/pending-requests';

const community = '019a0000-0000-7000-8000-000000000001';
const house = '019a0000-0000-7000-8000-000000000002';
const billId = '019a0000-0000-7000-8000-000000000003';
const subject = '019a0000-0000-7000-8000-000000000004';
const base = `/api/property/v1/communities/${community}`;
const route = `/property/communities/${community}/bills`;
const timestamp = '2026-10-16T00:00:00Z';
const session: SessionResponse = {
  scope: 'property_admin',
  subject_id: subject,
  login_name: 'property',
  display_name: '管理员',
  must_change_password: false,
  csrf_token: 'billing-csrf',
  permissions: [
    'property.community.read',
    'property.house.read',
    'property.bill.read',
    'property.bill.create',
    'property.bill.update',
    'property.bill.void',
    'property.bill_receipt.create',
    'property.bill_receipt.correct',
  ],
};
const bill: Bill = {
  id: billId,
  property_company_id: community,
  community_id: community,
  house_id: house,
  bill_type: 'property_fee',
  period_granularity: 'month',
  billing_month: '2024-01',
  period_start: '2024-01-01',
  period_end: '2024-02-01',
  external_bill_no: null,
  basis_version_id: null,
  amount_source: 'manual',
  calculation_rule_version: null,
  receivable_cents: 10000,
  settled_cents: 3000,
  outstanding_cents: 7000,
  lifecycle_status: 'active',
  settlement_status: 'partially_settled',
  due_date: null,
  is_overdue: false,
  house_label_snapshot: '春日小区／一号楼／101',
  manual_amount_reason: '历史补录',
  void_reason: null,
  voided_at: null,
  voided_by: null,
  row_version: 1,
  created_by: subject,
  created_at: timestamp,
  updated_at: timestamp,
  basis: null,
  house_effective_enabled: true,
  payment_in_progress: false,
};
const result: BillWriteResult = {
  bill,
  operation: {
    id: billId,
    bill_id: billId,
    action: 'create',
    bill_version: 1,
    actor_type: 'admin',
    actor_id: subject,
    actor_name: '管理员',
    reason: null,
    request_id: 'request',
    created_at: timestamp,
  },
  settlement_entries: [],
};
function mockBilling(
  unknownWrite = false,
  history: {
    bill?: Bill;
    entries?: SettlementEntry[];
    operations?: BillOperation[];
  } = {},
) {
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    const target = new URL(String(url), window.location.origin);
    const path = target.pathname;
    const page = <T,>(items: T[]) =>
      Response.json({
        items,
        total: items.length,
        page: Number(target.searchParams.get('page') || 1),
        page_size: Number(target.searchParams.get('page_size') || 20),
      });
    if (path.endsWith('/admin-sessions/current')) return Response.json(session);
    if (path.endsWith('/property-companies/current'))
      return Response.json({ id: community, name: '物业公司', enabled: true });
    if (path.endsWith('/property-workspace/summary'))
      return Response.json({
        billing_month: '2026-10',
        pending_house_claims: 0,
        monthly_receivable_cents: 0,
        monthly_settled_cents: 0,
        pending_reconciliation_count: 0,
      });
    const communityData = {
      id: community,
      property_company_id: community,
      property_company_name: '物业公司',
      name: '春日小区',
      code: 'SPRING',
      address: '地址',
      enabled: true,
      created_at: timestamp,
      updated_at: timestamp,
    };
    if (path === '/api/property/v1/communities') return page([communityData]);
    if (path === base) return Response.json(communityData);
    if (path === `${base}/houses`)
      return page([
        {
          id: house,
          community_id: community,
          room_no: '101',
          display_address: bill.house_label_snapshot,
          effective_enabled: true,
          enabled: true,
        },
      ]);
    if (path === `${base}/bills`) {
      if (init?.method === 'POST') {
        if (unknownWrite) throw new TypeError('network lost after submission');
        return Response.json(result, { status: 201 });
      }
      return page([history.bill ?? bill]);
    }
    if (path === `${base}/bills/${billId}`)
      return Response.json(history.bill ?? bill);
    if (path.endsWith('/settlement-entries'))
      return page(history.entries ?? []);
    if (path.endsWith('/operations')) return page(history.operations ?? []);
    if (path.endsWith('/offline-receipts') && init?.method === 'POST') {
      if (unknownWrite) throw new TypeError('network lost after submission');
      return Response.json(
        {
          ...result,
          bill: {
            ...bill,
            settled_cents: 10000,
            outstanding_cents: 0,
            settlement_status: 'settled',
            row_version: 2,
          },
        },
        { status: 201 },
      );
    }
    if (path.includes('/bill-operation-results/'))
      return Response.json({ response_status: 201, result });
    if (path.endsWith('/admin-sessions/current') && init?.method === 'DELETE')
      return new Response(null, { status: 204 });
    throw new Error(`Unexpected request ${path}`);
  });
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}
afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe('property billing screens', () => {
  it('shows payment occupation and prevents conflicting writes while allowing metadata changes', async () => {
    const fetcher = mockBilling(false, {
      bill: {
        ...bill,
        settled_cents: 0,
        outstanding_cents: 10000,
        settlement_status: 'unpaid',
        payment_in_progress: true,
      },
    });
    renderRoutes(`${route}/${billId}`);
    await screen.findByText('该账单有支付正在处理中');
    expect(screen.getByText('支付处理中')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '登记线下收款' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '作废账单' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '修改资料' })).toBeEnabled();
    expect(fetcher.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(
      false,
    );
  });

  it('shows system online receipts without offering offline corrections or reversals', async () => {
    mockBilling(false, {
      entries: [
        {
          id: `${billId.slice(0, -1)}5`,
          bill_id: billId,
          operation_id: billId,
          entry_type: 'receipt',
          source_type: 'online_payment',
          payment_order_item_id: house,
          amount_cents: 3000,
          reverses_entry_id: null,
          reversed_by_entry_id: null,
          received_on: '2026-10-16',
          created_at: timestamp,
          actor_type: 'system',
          actor_id: null,
          actor_name: '系统',
          reason: null,
        },
      ],
      operations: [
        {
          ...result.operation,
          action: 'online_receipt',
          actor_type: 'system',
          actor_id: null,
          actor_name: '系统',
        },
      ],
    });
    renderRoutes(`${route}/${billId}`);
    await screen.findByText('线上支付');
    expect(screen.getByText('系统')).toBeInTheDocument();
    expect(screen.getByText(house)).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '纠错' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '撤销误登记' }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: '操作历史' }));
    await screen.findByText('线上收款入账');
    expect(screen.getAllByText('系统').length).toBeGreaterThan(0);
  });

  it('keeps offline correction controls available only when the bill has no payment occupation', async () => {
    const entry: SettlementEntry = {
      id: `${billId.slice(0, -1)}5`,
      bill_id: billId,
      operation_id: billId,
      entry_type: 'receipt',
      source_type: 'offline',
      payment_order_item_id: null,
      amount_cents: 3000,
      reverses_entry_id: null,
      reversed_by_entry_id: null,
      received_on: null,
      created_at: timestamp,
      actor_type: 'admin',
      actor_id: subject,
      actor_name: '管理员',
      reason: null,
    };
    mockBilling(false, { entries: [entry] });
    const view = renderRoutes(`${route}/${billId}`);
    expect(await screen.findByRole('button', { name: '纠错' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '撤销误登记' })).toBeEnabled();
    expect(screen.getByText('线下登记')).toBeInTheDocument();
    view.unmount();
    mockBilling(false, {
      bill: { ...bill, payment_in_progress: true },
      entries: [entry],
    });
    renderRoutes(`${route}/${billId}`);
    await screen.findByText('线下登记');
    expect(
      screen.queryByRole('button', { name: '纠错' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '撤销误登记' }),
    ).not.toBeInTheDocument();
  });

  it('blocks an open receipt form after a refresh discovers payment occupation without a version change', async () => {
    const fetcher = mockBilling();
    const fallback = fetcher.getMockImplementation()!;
    let occupied = false;
    fetcher.mockImplementation(async (url, init) =>
      new URL(String(url)).pathname === `${base}/bills/${billId}`
        ? Response.json({ ...bill, payment_in_progress: occupied })
        : fallback(url, init),
    );
    renderRoutes(`${route}/${billId}`);
    fireEvent.click(
      await screen.findByRole('button', { name: '登记线下收款' }),
    );
    const drawer = within(await screen.findByRole('dialog'));
    fireEvent.click(drawer.getByRole('button', { name: '填入剩余金额' }));
    occupied = true;
    fireEvent.click(drawer.getByRole('button', { name: '刷新账单并重新核对' }));
    await drawer.findByText('该账单有支付正在处理中，请先核实原订单');
    expect(drawer.getByRole('button', { name: '确认保存' })).toBeDisabled();
    expect(
      fetcher.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith('/offline-receipts') && init?.method === 'POST',
      ),
    ).toBe(false);
  });

  it('defaults to pending bills across all months and restores URL filters', async () => {
    const fetcher = mockBilling();
    renderRoutes(`${route}?external_bill_no=001a&page=2`);
    await screen.findByRole('link', { name: '账单详情' }, { timeout: 3000 });
    const call = fetcher.mock.calls.find(
      ([url]) => new URL(String(url)).pathname === `${base}/bills`,
    )!;
    const target = new URL(String(call[0]));
    expect(target.searchParams.get('outstanding_only')).toBe('true');
    expect(target.searchParams.has('billing_month_from')).toBe(false);
    expect(target.searchParams.get('external_bill_no')).toBe('001a');
    expect(target.searchParams.get('page')).toBe('2');
    expect(screen.getByDisplayValue('001a')).toBeInTheDocument();
  });
  it('registers the remaining amount with a version and idempotency key', async () => {
    const fetcher = mockBilling();
    renderRoutes(`${route}/${billId}`);
    fireEvent.click(
      await screen.findByRole('button', { name: '登记线下收款' }),
    );
    const drawer = within(await screen.findByRole('dialog'));
    fireEvent.click(drawer.getByRole('button', { name: '填入剩余金额' }));
    expect(drawer.getByLabelText('本次收款（元）')).toHaveValue('70.00');
    fireEvent.click(drawer.getByRole('button', { name: '确认保存' }));
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith('/offline-receipts') &&
            init?.method === 'POST',
        ),
      ).toBe(true),
    );
    const call = fetcher.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith('/offline-receipts') && init?.method === 'POST',
    )!;
    expect(JSON.parse(String(call[1]?.body))).toMatchObject({
      amount_cents: 7000,
      expected_row_version: 1,
      received_on: null,
    });
    expect(new Headers(call[1]?.headers).get('Idempotency-Key')).toMatch(
      /^[a-f0-9-]+$/,
    );
    await waitFor(() =>
      expect(pendingSnapshot('property_admin', subject)).toBe('[]'),
    );
  });
  it('preserves a submitted request after network failure and recovers after reload', async () => {
    vi.stubGlobal('crypto', {
      getRandomValues: crypto.getRandomValues.bind(crypto),
    });
    const fetcher = mockBilling(true);
    const view = renderRoutes(`${route}/${billId}`);
    fireEvent.click(
      await screen.findByRole('button', { name: '登记线下收款' }),
    );
    const drawer = within(await screen.findByRole('dialog'));
    fireEvent.click(drawer.getByRole('button', { name: '填入剩余金额' }));
    fireEvent.click(drawer.getByRole('button', { name: '确认保存' }));
    await screen.findByText('请求未完成');
    const stored = JSON.parse(
      JSON.parse(pendingSnapshot('property_admin', subject))[0],
    );
    const sent = fetcher.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith('/offline-receipts') && init?.method === 'POST',
    )!;
    expect(stored.key).toBe(
      new Headers(sent[1]?.headers).get('Idempotency-Key'),
    );
    expect(stored.body.amount_cents).toBe(7000);
    view.unmount();
    renderRoutes(route);
    fireEvent.click(await screen.findByRole('button', { name: '核实结果' }));
    await screen.findByText('操作已确认');
    expect(pendingSnapshot('property_admin', subject)).toBe('[]');
    expect(
      fetcher.mock.calls.filter(
        ([url, init]) =>
          String(url).endsWith('/offline-receipts') && init?.method === 'POST',
      ),
    ).toHaveLength(1);
  });
  it('creates a manual bill when randomUUID is unavailable on HTTP', async () => {
    vi.stubGlobal('crypto', {
      getRandomValues: crypto.getRandomValues.bind(crypto),
    });
    const fetcher = mockBilling();
    renderRoutes(route);
    fireEvent.click(await screen.findByRole('button', { name: '新增账单' }));
    const drawer = within(await screen.findByRole('dialog'));
    fireEvent.mouseDown(drawer.getByRole('combobox', { name: '房屋' }));
    fireEvent.click(
      await screen.findByText(bill.house_label_snapshot, {
        selector: '.ant-select-item-option-content',
      }),
    );
    fireEvent.change(drawer.getByLabelText('账单月份'), {
      target: { value: '2024-01' },
    });
    fireEvent.change(drawer.getByLabelText('应收金额（元）'), {
      target: { value: '120' },
    });
    fireEvent.change(drawer.getByLabelText('手填金额原因'), {
      target: { value: '历史补录' },
    });
    await drawer.findByText('应收 ¥120.00，已缴 ¥0.00，待缴 ¥120.00');
    fireEvent.click(drawer.getByRole('button', { name: '确认保存' }));
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith('/bills') && init?.method === 'POST',
        ),
        screen.queryByRole('dialog')?.textContent ?? undefined,
      ).toBe(true),
    );
    const call = fetcher.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith('/bills') && init?.method === 'POST',
    )!;
    expect(JSON.parse(String(call[1]?.body))).toMatchObject({
      house_id: house,
      amount_source: 'manual',
      receivable_cents: 12000,
    });
    expect(new Headers(call[1]?.headers).get('Idempotency-Key')).toMatch(
      /^[A-Za-z0-9_-]{1,128}$/,
    );
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId('location')).toHaveTextContent(
      `${route}/${billId}`,
    );
    expect(screen.queryByText('放弃未保存的修改？')).not.toBeInTheDocument();
    expect(pendingSnapshot('property_admin', subject)).toBe('[]');
    expect(screen.queryByText('请求未完成')).not.toBeInTheDocument();
  });
  it('creates a manual zero bill without a basis and enforces the reason boundary', async () => {
    const fetcher = mockBilling();
    renderRoutes(route);
    fireEvent.click(await screen.findByRole('button', { name: '新增账单' }));
    const drawer = within(await screen.findByRole('dialog'));
    fireEvent.mouseDown(drawer.getByRole('combobox', { name: '房屋' }));
    fireEvent.click(
      await screen.findByText(bill.house_label_snapshot, {
        selector: '.ant-select-item-option-content',
      }),
    );
    fireEvent.change(drawer.getByLabelText('账单月份'), {
      target: { value: '2024-01' },
    });
    fireEvent.change(drawer.getByLabelText('应收金额（元）'), {
      target: { value: '0' },
    });
    fireEvent.change(drawer.getByLabelText('手填金额原因'), {
      target: { value: '🏠'.repeat(1001) },
    });
    fireEvent.click(drawer.getByRole('button', { name: '确认保存' }));
    await drawer.findByText('最多 1000 个字符');
    expect(
      fetcher.mock.calls.some(
        ([url, init]) =>
          String(url).endsWith('/bills') && init?.method === 'POST',
      ),
    ).toBe(false);
    fireEvent.change(drawer.getByLabelText('手填金额原因'), {
      target: { value: '🏠'.repeat(1000) },
    });
    fireEvent.click(drawer.getByRole('button', { name: '确认保存' }));
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith('/bills') && init?.method === 'POST',
        ),
      ).toBe(true),
    );
    const call = fetcher.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith('/bills') && init?.method === 'POST',
    )!;
    const body = JSON.parse(String(call[1]?.body));
    expect(body).toMatchObject({
      amount_source: 'manual',
      receivable_cents: 0,
      basis_version_id: null,
      manual_amount_reason: '🏠'.repeat(1000),
    });
    expect(body.initial_receipt).toBeUndefined();
  });
  it('uses the new month preview when an older calculation arrives late', async () => {
    const fetcher = mockBilling();
    const fallback = fetcher.getMockImplementation()!;
    let resolveOld!: (response: Response) => void;
    const old = new Promise<Response>((resolve) => {
      resolveOld = resolve;
    });
    const basis = {
      id: house,
      house_id: house,
      version_no: 1,
      effective_from_month: '2024-01',
      house_usage: 'residential',
      area_sqm: null,
      unit_price_cents: null,
      fixed_amount_cents: 9000,
      change_reason: '初始',
      created_by: subject,
      created_at: timestamp,
    };
    const calculation = (month: string, cents: number) => ({
      available: true,
      billing_month: month,
      period_start: `${month}-01`,
      period_end: '2024-03-01',
      house_label_snapshot: bill.house_label_snapshot,
      basis: {
        ...basis,
        id: cents === 9000 ? house : billId,
        fixed_amount_cents: cents,
      },
      calculation_method: 'fixed',
      calculation_rule_version: 1,
      receivable_cents: cents,
    });
    fetcher.mockImplementation(async (url, init) => {
      if (String(url).endsWith('/admin-sessions/current'))
        return Response.json({
          ...session,
          permissions: [...session.permissions, 'property.fee_basis.read'],
        });
      if (String(url).endsWith('/property-fee-calculations')) {
        const month = JSON.parse(String(init?.body)).billing_month;
        return month === '2024-01'
          ? old
          : Response.json(calculation(month, 5000));
      }
      return fallback(url, init);
    });
    renderRoutes(route);
    fireEvent.click(await screen.findByRole('button', { name: '新增账单' }));
    const drawer = within(await screen.findByRole('dialog'));
    fireEvent.mouseDown(drawer.getByRole('combobox', { name: '房屋' }));
    fireEvent.click(
      await screen.findByText(bill.house_label_snapshot, {
        selector: '.ant-select-item-option-content',
      }),
    );
    fireEvent.change(drawer.getByLabelText('账单月份'), {
      target: { value: '2024-01' },
    });
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith('/property-fee-calculations') &&
            JSON.parse(String(init?.body)).billing_month === '2024-01',
        ),
      ).toBe(true),
    );
    fireEvent.change(drawer.getByLabelText('账单月份'), {
      target: { value: '2024-02' },
    });
    await drawer.findByText('¥50.00', { selector: 'strong' });
    await act(async () =>
      resolveOld(Response.json(calculation('2024-01', 9000))),
    );
    expect(
      drawer.getByText('¥50.00', { selector: 'strong' }),
    ).toBeInTheDocument();
    expect(
      drawer.queryByText('¥90.00', { selector: 'strong' }),
    ).not.toBeInTheDocument();
    fireEvent.click(drawer.getByRole('button', { name: '确认保存' }));
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith('/bills') && init?.method === 'POST',
        ),
      ).toBe(true),
    );
    const call = fetcher.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith('/bills') && init?.method === 'POST',
    )!;
    expect(JSON.parse(String(call[1]?.body))).toMatchObject({
      billing_month: '2024-02',
      basis_version_id: billId,
      expected_receivable_cents: 5000,
    });
  });

  it('submits the current manual amount and full receipt after an immediate edit', async () => {
    const fetcher = mockBilling();
    renderRoutes(route);
    fireEvent.click(await screen.findByRole('button', { name: '新增账单' }));
    const drawer = within(await screen.findByRole('dialog'));
    fireEvent.mouseDown(drawer.getByRole('combobox', { name: '房屋' }));
    fireEvent.click(
      await screen.findByText(bill.house_label_snapshot, {
        selector: '.ant-select-item-option-content',
      }),
    );
    fireEvent.change(drawer.getByLabelText('账单月份'), {
      target: { value: '2024-01' },
    });
    fireEvent.change(drawer.getByLabelText('手填金额原因'), {
      target: { value: '历史已缴' },
    });
    fireEvent.change(drawer.getByLabelText('应收金额（元）'), {
      target: { value: '10.00' },
    });
    fireEvent.mouseDown(drawer.getByRole('combobox', { name: '线下已缴' }));
    fireEvent.click(
      await screen.findByText('全额已缴', {
        selector: '.ant-select-item-option-content',
      }),
    );
    await drawer.findByText('将登记全额收款 10.00 元');
    fireEvent.change(drawer.getByLabelText('应收金额（元）'), {
      target: { value: '25.01' },
    });
    fireEvent.click(drawer.getByRole('button', { name: '确认保存' }));
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith('/bills') && init?.method === 'POST',
        ),
      ).toBe(true),
    );
    const call = fetcher.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith('/bills') && init?.method === 'POST',
    )!;
    expect(JSON.parse(String(call[1]?.body))).toMatchObject({
      receivable_cents: 2501,
      initial_receipt: { amount_cents: 2501 },
    });
  });

  it('adds an immutable fixed-zero basis version from the house tab', async () => {
    const fetcher = mockBilling();
    const fallback = fetcher.getMockImplementation()!;
    const basis = {
      id: billId,
      house_id: house,
      version_no: 1,
      effective_from_month: '2024-01',
      house_usage: 'residential',
      area_sqm: null,
      unit_price_cents: null,
      fixed_amount_cents: 0,
      change_reason: '初始',
      created_by: subject,
      created_at: timestamp,
    };
    fetcher.mockImplementation(async (url, init) => {
      const target = new URL(String(url));
      if (target.pathname.endsWith('/admin-sessions/current'))
        return Response.json({
          ...session,
          permissions: [
            ...session.permissions,
            'property.fee_basis.read',
            'property.fee_basis.create',
          ],
        });
      if (target.pathname === `${base}/houses/${house}`)
        return Response.json({
          id: house,
          community_id: community,
          space_node_id: house,
          room_no: '101',
          floor_no: 1,
          external_code: null,
          display_address: bill.house_label_snapshot,
          enabled: true,
          effective_enabled: true,
          created_at: timestamp,
          updated_at: timestamp,
        });
      if (target.pathname.endsWith('/property-fee-basis-versions'))
        return init?.method === 'POST'
          ? Response.json({ ...basis, version_no: 2 }, { status: 201 })
          : Response.json({
              items: [basis],
              total: 1,
              page: 1,
              page_size: Number(target.searchParams.get('page_size') || 20),
            });
      if (target.pathname.endsWith('/property-fee-calculations'))
        return Response.json({
          available: true,
          billing_month: '2026-10',
          house_label_snapshot: bill.house_label_snapshot,
          basis,
          receivable_cents: 0,
        });
      return fallback(url, init);
    });
    renderRoutes(
      `/property/communities/${community}/houses/${house}?tab=basis`,
    );
    const add = await screen.findByRole('button', { name: '新增依据版本' });
    await waitFor(() => expect(add).toBeEnabled());
    fireEvent.click(add);
    const drawer = within(await screen.findByRole('dialog'));
    fireEvent.change(
      drawer.getByLabelText('固定月金额（元，可填 0，留空按面积计算）'),
      { target: { value: '0' } },
    );
    fireEvent.change(drawer.getByLabelText('变更原因'), {
      target: { value: '确认免收' },
    });
    fireEvent.click(drawer.getByRole('button', { name: '保存新版本' }));
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(
          ([url, init]) =>
            String(url).endsWith('/property-fee-basis-versions') &&
            init?.method === 'POST',
        ),
        document.querySelector('.ant-drawer-body')?.textContent ?? undefined,
      ).toBe(true),
    );
    const call = fetcher.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith('/property-fee-basis-versions') &&
        init?.method === 'POST',
    )!;
    expect(JSON.parse(String(call[1]?.body))).toMatchObject({
      expected_latest_version_no: 1,
      fixed_amount_cents: 0,
      area_sqm: null,
      unit_price_cents: null,
      change_reason: '确认免收',
    });
  });
  it('isolates recovery by account and scope', async () => {
    savePending('platform_admin', subject, 'other-scope', {
      kind: 'bill',
      key: 'other-scope',
      label: '平台数据',
    });
    savePending('property_admin', 'other-user', 'other-user', {
      kind: 'bill',
      key: 'other-user',
      label: '他人数据',
    });
    mockBilling();
    renderRoutes(route);
    await screen.findByRole('button', { name: '新增账单' });
    expect(screen.queryByText('待核实的账单操作')).not.toBeInTheDocument();
  });
});
