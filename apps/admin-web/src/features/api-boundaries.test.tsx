import { renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { AdminScopeProvider } from '../auth/AdminScopeProvider';
import type { AdminScope } from '../shared/admin-types';
import { usePlatformAdminApi } from './platform/hooks';
import { usePropertyOnboardingApi } from './platform/property/hooks';
import { createPropertyWorkspaceApi } from './property/api';
import { usePropertyWorkspaceApi } from './property/hooks';

describe('application API boundaries', () => {
  it.each([
    ['property_admin', usePlatformAdminApi],
    ['property_admin', usePropertyOnboardingApi],
    ['platform_admin', usePropertyWorkspaceApi],
  ] as const)(
    'rejects a business API in the foreign %s context',
    (scope: AdminScope, hook) => {
      const wrapper = ({ children }: { children: ReactNode }) => (
        <AdminScopeProvider
          scope={scope}
          apiBase={
            scope === 'platform_admin' ? '/api/platform' : '/api/property'
          }
        >
          {children}
        </AdminScopeProvider>
      );
      expect(() => renderHook(() => hook(), { wrapper })).toThrow(
        /business requires/,
      );
    },
  );

  it('keeps company scope out of property queries and exposes no platform mutations', async () => {
    const requests: string[] = [];
    const api = createPropertyWorkspaceApi(async <T,>(path: string) => {
      requests.push(path);
      return undefined as T;
    });
    const filters = {
      page: 1,
      page_size: 20,
      name: '本公司',
      property_company_id: 'foreign',
    };
    await api.communities(filters);
    const path = requests[0];
    expect(
      new URL(String(path), 'https://property.invalid').searchParams.has(
        'property_company_id',
      ),
    ).toBe(false);
    for (const method of [
      'createCompany',
      'updateCompany',
      'createAdmin',
      'createCommunity',
      'updateCommunity',
    ]) {
      expect(api).not.toHaveProperty(method);
    }
  });
});
