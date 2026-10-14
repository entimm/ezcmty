import { ProFormSelect } from '@ant-design/pro-components';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { Form } from 'antd';
import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PermissionGuard } from '@/components/PermissionGuard';
import { AdminScopeProvider } from '@/auth/AdminScopeProvider';
import type { AdminScope } from '@/shared/admin-types';
import type { AdminSessionContextValue } from '@/auth/session-context';
import { useAdminSession } from '@/auth/use-admin-session';

afterEach(() => vi.unstubAllGlobals());

function renderScopes(withOptions = false) {
  const sessions = {} as Record<AdminScope, AdminSessionContextValue>;
  const queries = {} as Record<AdminScope, QueryClient>;
  const optionRequests = {
    platform_admin: vi.fn(async () => [
      { label: '平台选项', value: 'platform' },
    ]),
    property_admin: vi.fn(async () => [
      { label: '物业选项', value: 'property' },
    ]),
  };

  function Probe() {
    const context = useAdminSession();
    sessions[context.scope] = context;
    queries[context.scope] = useQueryClient();
    return (
      <>
        <PermissionGuard permission="reports.read">
          <span>{context.scope} report</span>
        </PermissionGuard>
        {withOptions && (
          <Form>
            <ProFormSelect
              name="shared-options"
              proFieldProps={{ proFieldKey: 'shared-options' }}
              request={optionRequests[context.scope]}
            />
          </Form>
        )}
      </>
    );
  }

  const view = render(
    <>
      <AdminScopeProvider scope="platform_admin" apiBase="/api/platform">
        <Probe />
      </AdminScopeProvider>
      <AdminScopeProvider scope="property_admin" apiBase="/api/property">
        <Probe />
      </AdminScopeProvider>
    </>,
  );
  return { sessions, queries, optionRequests, ...view };
}

function login(context: AdminSessionContextValue, permissions: string[] = []) {
  context.setSession({
    scope: context.scope,
    subjectId: `${context.scope}-user`,
    permissions,
    loginName: 'tester',
    displayName: '测试管理员',
    mustChangePassword: false,
    csrfToken: 'test-csrf',
  });
}

describe('admin scope isolation', () => {
  it('starts unauthenticated and rejects a session from another scope', () => {
    const { sessions } = renderScopes();
    expect(sessions.platform_admin.session).toBeNull();
    expect(sessions.property_admin.session).toBeNull();
    expect(() =>
      sessions.platform_admin.setSession({
        scope: 'property_admin',
        subjectId: 'property-user',
        permissions: [],
        loginName: 'tester',
        displayName: '测试管理员',
        mustChangePassword: false,
        csrfToken: 'test-csrf',
      }),
    ).toThrow('Session scope');
  });

  it('uses the permission context of the current scope', () => {
    const { sessions } = renderScopes();
    act(() => {
      login(sessions.platform_admin, ['reports.read']);
      login(sessions.property_admin);
    });
    expect(screen.getByText('platform_admin report')).toBeInTheDocument();
    expect(screen.queryByText('property_admin report')).not.toBeInTheDocument();
    expect(screen.getByText('无权访问此页面')).toBeInTheDocument();
  });

  it('isolates identical React Query keys and clears only the changed identity', () => {
    const { sessions, queries } = renderScopes();
    queries.platform_admin.setQueryData(['resources'], 'platform-data');
    queries.property_admin.setQueryData(['resources'], 'property-data');
    expect(queries.platform_admin).not.toBe(queries.property_admin);
    expect(queries.platform_admin.getQueryData(['resources'])).toBe(
      'platform-data',
    );
    act(() => login(sessions.platform_admin));
    expect(queries.platform_admin.getQueryData(['resources'])).toBeUndefined();
    expect(queries.property_admin.getQueryData(['resources'])).toBe(
      'property-data',
    );
  });

  it('isolates ProComponents option caches and resets only the changed identity', async () => {
    const { sessions, optionRequests } = renderScopes(true);
    await waitFor(() => {
      expect(optionRequests.platform_admin).toHaveBeenCalledOnce();
      expect(optionRequests.property_admin).toHaveBeenCalledOnce();
    });
    act(() => login(sessions.platform_admin));
    await waitFor(() =>
      expect(optionRequests.platform_admin).toHaveBeenCalledTimes(2),
    );
    expect(optionRequests.property_admin).toHaveBeenCalledOnce();
  });

  it('clears only the scope receiving a 401 and keeps the other session usable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(null, { status: 401 })),
    );
    const { sessions, queries } = renderScopes();
    act(() => {
      login(sessions.platform_admin, ['reports.read']);
      login(sessions.property_admin, ['reports.read']);
    });
    queries.platform_admin.setQueryData(['resources'], 'platform-data');
    queries.property_admin.setQueryData(['resources'], 'property-data');
    await act(async () => {
      await expect(
        sessions.platform_admin.request('/v1/resources'),
      ).rejects.toMatchObject({ status: 401 });
    });
    expect(sessions.platform_admin.session).toBeNull();
    expect(queries.platform_admin.getQueryData(['resources'])).toBeUndefined();
    expect(sessions.property_admin.session?.subjectId).toBe(
      'property_admin-user',
    );
    expect(queries.property_admin.getQueryData(['resources'])).toBe(
      'property-data',
    );
    expect(screen.getByText('property_admin report')).toBeInTheDocument();
  });
});
