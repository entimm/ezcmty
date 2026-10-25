import { useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App, Form } from 'antd';
import { describe, expect, it, vi } from 'vitest';
import {
  AdminContext,
  type AdminContextValue,
} from '../../../src/shared/context';
import type { AdminRequest, RequestOptions } from '../../../src/shared/request';
import type { Permission } from '../../../src/shared/system/api';
import {
  PermissionEditor,
  SystemPages,
} from '../../../src/shared/system/SystemPages';
import { canImport } from '../../../src/shared/imports/authorization';

const catalog: Permission[] = [
  {
    code: 'property.bill.read',
    name: '查看物业费账单',
    group: '物业费账单',
    level: '查看',
    requires: [],
    assignable: true,
  },
  {
    code: 'property.bill.manage',
    name: '经办物业费账单',
    group: '物业费账单',
    level: '经办',
    requires: ['property.bill.read'],
    assignable: true,
  },
  {
    code: 'property.bill.void',
    name: '作废账单',
    group: '账单作废',
    level: '关键操作',
    requires: ['property.bill.read'],
    assignable: true,
  },
];
function show(
  element: React.ReactNode,
  request: AdminRequest,
  permissions = ['property.system.read', 'property.system.manage'],
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const context: AdminContextValue = {
    scope: 'property',
    request,
    can: (code) => permissions.includes(code),
    hasPermission: (code) => permissions.includes(code),
    session: {
      scope: 'property_admin',
      subjectId: 'self',
      loginName: 'admin',
      displayName: '物业管理员',
      permissions,
      mustChangePassword: false,
      csrfToken: 'csrf',
    },
    refreshSession: vi.fn().mockResolvedValue(undefined),
    communityId: 'community',
    communities: [],
    go: vi.fn(),
    page: 'roles',
    params: {},
    setDirty: vi.fn(),
    confirmLeave: (next) => next(),
  };
  render(
    <QueryClientProvider client={client}>
      <AdminContext.Provider value={context}>
        <App>{element}</App>
      </AdminContext.Provider>
    </QueryClientProvider>,
  );
  return client;
}
function PermissionFixture() {
  const [form] = Form.useForm();
  const [snapshot, setSnapshot] = useState<string[]>([]);
  return (
    <Form form={form} initialValues={{ permissions: [] }}>
      <PermissionEditor
        permissions={catalog}
        form={form}
        changed={() => setSnapshot(form.getFieldValue('permissions'))}
      />
      <output data-testid="permissions">{JSON.stringify(snapshot)}</output>
    </Form>
  );
}

describe('业务能力授权与岗位模板', () => {
  it('经办自动包含查看，独立作废默认关闭；移除查看时同步移除依赖操作', async () => {
    show(<PermissionFixture />, vi.fn() as AdminRequest);
    expect(
      screen.getByRole('checkbox', { name: '作废账单' }),
    ).not.toBeChecked();
    fireEvent.mouseDown(
      screen.getByRole('combobox', { name: '物业费账单授权级别' }),
    );
    fireEvent.click(
      await screen.findByText('经办', {
        selector: '.ant-select-item-option-content',
      }),
    );
    expect(screen.getByTestId('permissions')).toHaveTextContent(
      'property.bill.manage',
    );
    expect(screen.getByTestId('permissions')).toHaveTextContent(
      'property.bill.read',
    );
    expect(
      screen.getByRole('checkbox', { name: '作废账单' }),
    ).not.toBeChecked();
    fireEvent.click(screen.getByRole('checkbox', { name: '作废账单' }));
    expect(screen.getByTestId('permissions')).toHaveTextContent(
      'property.bill.void',
    );
    fireEvent.mouseDown(
      screen.getByRole('combobox', { name: '物业费账单授权级别' }),
    );
    fireEvent.click(
      await screen.findByText('无权限', {
        selector: '.ant-select-item-option-content',
      }),
    );
    expect(screen.getByTestId('permissions')).toHaveTextContent('[]');
    await waitFor(() =>
      expect(
        screen.getByRole('checkbox', { name: '作废账单' }),
      ).not.toBeChecked(),
    );
  });
  it('选用岗位模板后一次创建角色和规范化权限，不产生空角色配置步骤', async () => {
    const writes: Record<string, unknown>[] = [];
    const request = (async (path: string, options?: RequestOptions) => {
      if (path === '/v1/admin-permissions') return catalog;
      if (path === '/v1/admin-role-templates')
        return [
          {
            code: 'billing',
            name: '账单经办员',
            permissions: ['property.bill.manage', 'property.bill.read'],
          },
        ];
      if (path === '/v1/admin-roles' && options?.method === 'POST') {
        writes.push(JSON.parse(String(options.body)));
        return {
          id: 'role',
          code: 'billing',
          name: '收费岗位',
          permissions: ['property.bill.manage', 'property.bill.read'],
          affected_account_count: 0,
          enabled: true,
          is_system: false,
        };
      }
      if (path.startsWith('/v1/admin-roles?'))
        return { items: [], total: 0, page: 1, page_size: 8 };
      throw new Error(path);
    }) as AdminRequest;
    show(<SystemPages page="roles" params={{}} go={vi.fn()} />, request);
    fireEvent.click(await screen.findByRole('button', { name: /新建角色/ }));
    fireEvent.mouseDown(
      await screen.findByRole('combobox', { name: '岗位模板' }),
    );
    fireEvent.click(
      await screen.findByText('账单经办员', {
        selector: '.ant-select-item-option-content',
      }),
    );
    fireEvent.change(screen.getByRole('textbox', { name: '角色编码' }), {
      target: { value: 'billing' },
    });
    fireEvent.change(screen.getByRole('textbox', { name: '角色名称' }), {
      target: { value: '收费岗位' },
    });
    fireEvent.click(screen.getByRole('button', { name: /保\s*存/ }));
    await waitFor(() =>
      expect(writes).toEqual([
        {
          code: 'billing',
          name: '收费岗位',
          permissions: ['property.bill.manage', 'property.bill.read'],
        },
      ]),
    );
    expect(
      screen.queryByText(/尚未授予权限.*配置权限/),
    ).not.toBeInTheDocument();
  });
  it('物业系统资料只读账号使用本端查询缓存，不出现管理写操作', async () => {
    const request = (async (path: string) =>
      path === '/v1/admin-permissions'
        ? catalog
        : {
            items: [
              {
                id: 'account',
                scope: 'property_admin',
                login_name: 'viewer',
                display_name: '只读物业账号',
                enabled: true,
                must_change_password: false,
                created_at: '2026-10-25T00:00:00Z',
                roles: [],
                effective_permissions: [],
              },
            ],
            total: 1,
            page: 1,
            page_size: 8,
          }) as AdminRequest;
    const client = show(
      <SystemPages page="accounts" params={{}} go={vi.fn()} />,
      request,
      ['property.system.read'],
    );
    expect(await screen.findByText('只读物业账号')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /新建管理员|编\s*辑|更多操作/ }),
    ).not.toBeInTheDocument();
    expect(
      client
        .getQueryCache()
        .getAll()
        .every((query) => query.queryKey[0] === 'property'),
    ).toBe(true);
  });
});
describe('导入授权跟随目标业务', () => {
  it('账单维护覆盖导入完整处理，房产和关键操作不随之开放，查看可生成错误文件', () => {
    const viewer = (code: string) => code === 'property.bill.read';
    const writer = (code: string) =>
      ['property.bill.read', 'property.bill.manage'].includes(code);
    expect(canImport('property', viewer, 'generate_error_file', 'bills')).toBe(
      true,
    );
    expect(canImport('property', viewer, 'execute', 'bills')).toBe(false);
    for (const action of [
      'create',
      'upload',
      'precheck',
      'execute',
      'cancel',
      'retry',
      'recover',
    ])
      expect(canImport('property', writer, action, 'bills')).toBe(true);
    expect(canImport('property', writer, 'create', 'houses')).toBe(false);
    expect(canImport('platform', () => true, 'create', 'bills')).toBe(false);
    expect(canImport('property', () => false, 'download', 'bills')).toBe(false);
  });
});
