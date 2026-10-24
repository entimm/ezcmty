import { describe, expect, it, vi } from 'vitest';
import {
  createPlatformApi,
  queryString,
} from '../../../src/features/platform/api';
import type { AdminRequest } from '../../../src/shared/request';

function harness() {
  const request = vi.fn<AdminRequest>().mockResolvedValue(undefined);
  return { request, api: createPlatformApi(request as AdminRequest) };
}
describe('平台接口契约', () => {
  it('状态筛选保留 false，分页与名称按查询参数编码', async () => {
    const { api, request } = harness();
    await api.companies({
      enabled: false,
      page: 2,
      page_size: 8,
      name: '锦绣 & 华庭',
      code: undefined,
    });
    const url = new URL(request.mock.calls[0][0], 'https://platform.example');
    expect(url.pathname).toBe('/v1/property-companies');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      enabled: 'false',
      page: '2',
      page_size: '8',
      name: '锦绣 & 华庭',
    });
    expect(queryString({ zero: 0, empty: '', absent: undefined })).toBe(
      'zero=0',
    );
  });
  it('公司管理员始终绑定路径公司，创建请求不含角色或小区授权', async () => {
    const { api, request } = harness();
    await api.createCompanyAdmin('company-id', {
      login_name: 'admin',
      display_name: '管理员',
      password: 'temporary-password',
    });
    expect(request).toHaveBeenCalledWith(
      '/v1/property-companies/company-id/admin-accounts',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(JSON.parse(request.mock.calls[0][1]!.body as string)).toEqual({
      login_name: 'admin',
      display_name: '管理员',
      password: 'temporary-password',
    });
  });
  it('清空公司联系人发送显式 null，不会写入编码', async () => {
    const { api, request } = harness();
    await api.updateCompany('company-id', {
      contact_name: null,
      contact_phone: null,
    });
    expect(request).toHaveBeenCalledWith(
      '/v1/property-companies/company-id',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ contact_name: null, contact_phone: null }),
      }),
    );
  });
  it('管理员角色与角色权限使用各自 PUT 资源契约', async () => {
    const { api, request } = harness();
    await api.assignRoles('account-id', ['role-id']);
    await api.assignPermissions('role-id', ['property.company.read']);
    expect(request.mock.calls[0]).toEqual([
      '/v1/admin-accounts/account-id/roles',
      expect.objectContaining({
        method: 'PUT',
        body: '{"role_ids":["role-id"]}',
      }),
    ]);
    expect(request.mock.calls[1]).toEqual([
      '/v1/admin-roles/role-id/permissions',
      expect.objectContaining({
        method: 'PUT',
        body: '{"permissions":["property.company.read"]}',
      }),
    ]);
  });
  it('重置密码只提交密码，使用独立业务操作路径', async () => {
    const { api, request } = harness();
    await api.resetCompanyAdminPassword(
      'company-id',
      'account-id',
      'temporary-password',
    );
    expect(request).toHaveBeenCalledWith(
      '/v1/property-companies/company-id/admin-accounts/account-id/password-resets',
      expect.objectContaining({
        method: 'POST',
        body: '{"password":"temporary-password"}',
      }),
    );
  });
  it('审计按带时区区间和请求标识查询，不伪造全文检索', async () => {
    const { api, request } = harness();
    await api.audit({
      from_time: '2026-10-23T16:00:00.000Z',
      to_time: '2026-10-24T15:59:59.000Z',
      request_id: 'req_1',
      result: 'failure',
    });
    const query = new URL(request.mock.calls[0][0], 'https://platform.example')
      .searchParams;
    expect(query.get('from_time')).toBe('2026-10-23T16:00:00.000Z');
    expect(query.get('request_id')).toBe('req_1');
    expect(query.has('search')).toBe(false);
  });
});
