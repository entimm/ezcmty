import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App } from 'antd';
import { describe, expect, it, vi } from 'vitest';
import { SystemPages } from '../../../src/features/platform/SystemPages';
import {
  AdminContext,
  type AdminContextValue,
} from '../../../src/shared/context';
import type { AdminRequest } from '../../../src/shared/request';

function show(page: string, permissions: string[], data: unknown) {
  const request = vi.fn().mockResolvedValue(data);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const context: AdminContextValue = {
    scope: 'platform',
    request: request as AdminRequest,
    can: (permission) => permissions.includes(permission),
    hasPermission: (permission) => permissions.includes(permission),
    session: {
      scope: 'platform_admin',
      subjectId: 'self',
      loginName: 'admin',
      displayName: '管理员',
      permissions,
      mustChangePassword: false,
      csrfToken: 'csrf',
    },
    refreshSession: vi.fn().mockResolvedValue(undefined),
    communityId: '',
    communities: [],
    go: vi.fn(),
    page,
    params: {},
    setDirty: vi.fn(),
    confirmLeave: vi.fn(),
  };
  render(
    <QueryClientProvider client={queryClient}>
      <AdminContext.Provider value={context}>
        <App>
          <SystemPages page={page} params={{}} go={context.go} />
        </App>
      </AdminContext.Provider>
    </QueryClientProvider>,
  );
  return request;
}
describe('平台管理权限与保护边界', () => {
  it('无读取权限时不请求列表，也不暴露管理操作', async () => {
    const request = show('accounts', [], {});
    expect(screen.getByText('暂无访问权限')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /新建管理员/ }),
    ).not.toBeInTheDocument();
    expect(request).not.toHaveBeenCalled();
  });
  it('只读管理员可以查看账号，不显示创建、编辑和角色分配', async () => {
    show('accounts', ['admin.account.read'], {
      items: [
        {
          id: 'other',
          scope: 'platform_admin',
          login_name: 'observer',
          display_name: '只读账号',
          enabled: true,
          must_change_password: false,
          created_at: '2026-10-24T00:00:00Z',
          roles: [],
        },
      ],
      total: 1,
      page: 1,
      page_size: 8,
    });
    expect(await screen.findByText('只读账号')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /查\s*看/ })).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /编\s*辑|新建管理员|分配角色/ }),
    ).not.toBeInTheDocument();
  });
  it('即使有写权限，系统角色仍不能编辑、启停或配置权限', async () => {
    show(
      'roles',
      ['admin.role.read', 'admin.role.update', 'admin.role.assign_permissions'],
      {
        items: [
          {
            id: 'system',
            code: 'super_admin',
            name: '系统超级管理员',
            enabled: true,
            is_system: true,
            permissions: ['admin.account.read'],
          },
        ],
        total: 1,
        page: 1,
        page_size: 8,
      },
    );
    expect(await screen.findByText('不可修改')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /配置权限|更多操作/ }),
    ).not.toBeInTheDocument();
  });
});
