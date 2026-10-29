import { PropertyBusinessBoundary } from '../../../src/features/property/runtime';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App, Form, Input } from 'antd';
import { describe, expect, it, vi } from 'vitest';
import {
  AdminContext,
  type AdminContextValue,
} from '../../../src/shared/context';
import type { AdminRequest, RequestOptions } from '../../../src/shared/request';
import { PropertyEditor } from '../../../src/features/property/Editor';
import { HousingPage } from '../../../src/shared/property-business/Housing';
import { BillModal } from '../../../src/shared/property-business/BillModal';
import { toCents } from '../../../src/shared/property-business/presentation';
import type { House, Owner } from '../../../src/features/property/api';

const firstHouse: House = {
  id: 'house-101',
  community_id: 'community-1',
  space_node_id: 'unit-1',
  room_no: '101',
  floor_no: 1,
  external_code: null,
  display_address: '锦绣华庭 · 1号楼 · 101',
  enabled: true,
  effective_enabled: true,
  created_at: '2026-10-01T02:00:00Z',
  updated_at: '2026-10-01T02:00:00Z',
};
const secondHouse: House = {
  ...firstHouse,
  id: 'house-202',
  room_no: '202',
  display_address: '锦绣华庭 · 1号楼 · 202',
};
function show(
  element: React.ReactNode,
  request?: AdminRequest,
  permissions?: string[],
) {
  const setDirty = vi.fn(),
    go = vi.fn();
  const can = (permission: string) =>
    !permissions || permissions.includes(permission);
  const context = {
    scope: 'property',
    session: { subjectId: 'property-user', permissions: permissions || [] },
    company: { id: 'company-1', name: '物业公司' },
    request: request ?? vi.fn(),
    can,
    hasPermission: can,
    communityId: 'community-1',
    community: { id: 'community-1', name: '锦绣华庭', enabled: true },
    params: {},
    setDirty,
    go,
    confirmLeave: (next: () => void) => next(),
  } as unknown as AdminContextValue;
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <AdminContext.Provider value={context}>
        <App>
          <PropertyBusinessBoundary>{element}</PropertyBusinessBoundary>
        </App>
      </AdminContext.Provider>
    </QueryClientProvider>,
  );
  return { setDirty, go };
}
function EditorFixture({ close }: { close: () => void }) {
  const [form] = Form.useForm();
  return (
    <PropertyEditor
      title="新增业主登记"
      form={form}
      initial={{ name: '' }}
      close={close}
      submit={async () => undefined}
    >
      <Form.Item name="name" label="业主姓名">
        <Input />
      </Form.Item>
    </PropertyEditor>
  );
}

describe('物业编辑与目标上下文', () => {
  it('空白表单点击遮罩直接关闭，清空输入后同样免确认', () => {
    const close = vi.fn();
    show(<EditorFixture close={close} />);
    fireEvent.change(screen.getByRole('textbox', { name: '业主姓名' }), {
      target: { value: '赵丽' },
    });
    fireEvent.change(screen.getByRole('textbox', { name: '业主姓名' }), {
      target: { value: '' },
    });
    const outside = document.querySelector('.ant-modal-wrap')!;
    fireEvent.mouseDown(outside);
    fireEvent.click(outside);
    expect(close).toHaveBeenCalledOnce();
    expect(screen.queryByText('有尚未保存的内容')).not.toBeInTheDocument();
  });
  it('有输入时在原弹窗确认，不嵌套弹窗', () => {
    const close = vi.fn();
    show(<EditorFixture close={close} />);
    fireEvent.change(screen.getByRole('textbox', { name: '业主姓名' }), {
      target: { value: '赵丽' },
    });
    fireEvent.click(screen.getByRole('button', { name: /取\s*消/ }));
    expect(close).not.toHaveBeenCalled();
    expect(screen.getByText('有尚未保存的内容')).toBeInTheDocument();
    expect(document.querySelectorAll('.ant-modal')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: '放弃并关闭' }));
    expect(close).toHaveBeenCalledOnce();
  });
  it('从第二套房屋快捷登记业主，只写入目标房屋并刷新列表', async () => {
    const owners = new Map<string, Owner[]>();
    const calls: { path: string; options?: RequestOptions }[] = [];
    const request = (async (path: string, options?: RequestOptions) => {
      calls.push({ path, options });
      const ownerId = path.match(/houses\/(house-\d+)\/owners/)?.[1];
      if (ownerId && options?.method === 'POST') {
        const input = JSON.parse(String(options.body)) as {
          name: string;
          phone: string;
        };
        const owner = {
          ...firstHouse,
          ...input,
          id: 'owner-new',
          house_id: ownerId,
        } satisfies Owner;
        owners.set(ownerId, [owner]);
        return owner;
      }
      if (ownerId)
        return {
          items: owners.get(ownerId) ?? [],
          total: owners.get(ownerId)?.length ?? 0,
          page: 1,
          page_size: 100,
        };
      if (path.startsWith('/v1/communities/community-1/houses?'))
        return {
          items: [firstHouse, secondHouse],
          total: 2,
          page: 1,
          page_size: 20,
        };
      throw new Error(`未声明的请求：${path}`);
    }) as AdminRequest;
    show(<HousingPage />, request, [
      'property.housing.read',
      'property.housing.read',
      'property.housing.manage',
    ]);
    const buttons = await screen.findAllByRole('button', { name: '登记业主' });
    fireEvent.click(buttons[1]);
    const dialog = screen.getByRole('dialog');
    expect(
      within(dialog).getByText(secondHouse.display_address),
    ).toBeInTheDocument();
    fireEvent.change(
      within(dialog).getByRole('textbox', { name: '业主姓名' }),
      { target: { value: '赵丽' } },
    );
    fireEvent.change(within(dialog).getByRole('textbox', { name: '手机号' }), {
      target: { value: '13812345678' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: '确认保存' }));
    await waitFor(() =>
      expect(
        calls.filter((call) => call.options?.method === 'POST'),
      ).toHaveLength(1),
    );
    expect(calls.find((call) => call.options?.method === 'POST')?.path).toBe(
      '/v1/communities/community-1/houses/house-202/owners',
    );
    await waitFor(() => expect(screen.getByText('赵丽')).toBeInTheDocument());
  });
});

describe('账单资金保护', () => {
  it.each([
    ['0', 0],
    ['0.01', 1],
    ['128.06', 12806],
    ['90071992547409.91', Number.MAX_SAFE_INTEGER],
  ])('金额 %s 精确转换为整数分', (value, expected) => {
    expect(toCents(value)).toBe(expected);
  });
  it.each(['-1', '1.001', '1e3', '90071992547409.92'])(
    '拒绝不可用金额 %s',
    (value) => {
      expect(() => toCents(value)).toThrow();
    },
  );
  it('新增账单未知结果不自动再写，手动重试保持原幂等键及金额快照', async () => {
    const writes: RequestOptions[] = [];
    const close = vi.fn();
    const request = (async (path: string, options?: RequestOptions) => {
      if (path.endsWith('/property-fee-calculations'))
        return {
          available: true,
          billing_month: '2026-11',
          calculation_rule_version: 1,
          receivable_cents: 40960,
          basis: {
            id: 'basis-3',
            version_no: 3,
            area_sqm: '128',
            unit_price_cents: 320,
            fixed_amount_cents: null,
          },
        };
      if (path.endsWith('/houses/house-101')) return firstHouse;
      if (path.includes('/house-options?'))
        return {
          items: [
            {
              id: firstHouse.id,
              community_id: firstHouse.community_id,
              label: firstHouse.display_address,
              enabled: true,
              effective_enabled: true,
            },
          ],
          total: 1,
          page: 1,
          page_size: 50,
        };
      if (path.endsWith('/bills') && options?.method === 'POST') {
        writes.push(options);
        if (writes.length === 1) throw new TypeError('网络中断');
        return {
          bill: { id: 'bill-new' },
          operation: {},
          settlement_entries: [],
        };
      }
      throw new Error(`未声明的请求：${path}`);
    }) as AdminRequest;
    show(<BillModal house={firstHouse} close={close} />, request);
    await screen.findByText(/依据 v3/);
    fireEvent.click(screen.getByRole('button', { name: '创建账单' }));
    await screen.findByText('正在核实原操作');
    expect(writes).toHaveLength(1);
    expect(close).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /取\s*消/ })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '重试原操作' }));
    await waitFor(() => expect(writes).toHaveLength(2));
    expect(writes[1].headers).toEqual(writes[0].headers);
    expect(writes[1].body).toBe(writes[0].body);
    expect(JSON.parse(String(writes[0].body))).toMatchObject({
      house_id: 'house-101',
      basis_version_id: 'basis-3',
      expected_receivable_cents: 40960,
      expected_calculation_rule_version: 1,
    });
    await waitFor(() => expect(close).toHaveBeenCalledOnce());
  });
});
