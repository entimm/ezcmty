import { describe, expect, it } from 'vitest';
import {
  configuredHosts,
  matchRoute,
  resolveScope,
  routePath,
  safeReturn,
} from '../../src/app/routes';

const company = '019a1234-5678-7abc-8def-0123456789ab';
const community = '019a1234-5678-7abc-9def-0123456789ab';
const house = '00000000-0000-4000-8000-000000000001';

describe('双后台域名与路由边界', () => {
  it.each(['/communities', '/payment-configuration'])(
    '关闭的物业页面%s不接受域名、本地或旧前缀直达，也不作为登录回跳目标',
    (path) => {
      expect(matchRoute('property', path, configuredHosts.property)).toBeNull();
      expect(
        matchRoute('property', '/property' + path, 'localhost'),
      ).toBeNull();
      expect(
        matchRoute('property', '/property' + path, configuredHosts.property),
      ).toBeNull();
      expect(safeReturn('property', path, configuredHosts.property)).toBe('/');
      expect(safeReturn('property', '/property' + path, 'localhost')).toBe(
        '/property',
      );
    },
  );
  it('专属域名只解析本端，未知域名不进入后台', () => {
    expect(resolveScope(configuredHosts.platform, '/companies')).toBe(
      'platform',
    );
    expect(
      resolveScope(configuredHosts.property.toUpperCase(), '/houses'),
    ).toBe('property');
    expect(resolveScope('untrusted.example', '/platform')).toBeNull();
  });
  it('本地入口使用完整路径段识别后台，拒绝相似前缀', () => {
    expect(resolveScope('localhost', '/')).toBe('portal');
    expect(resolveScope('127.0.0.1', '/platform')).toBe('platform');
    expect(resolveScope('localhost', '/property/houses')).toBe('property');
    expect(resolveScope('localhost', '/platform-evil')).toBeNull();
    expect(resolveScope('localhost', '/propertyXYZ')).toBeNull();
  });
  it('各域名与本地路径都不能进入另一后台的页面', () => {
    expect(
      matchRoute('platform', '/property/payments', configuredHosts.platform),
    ).toBeNull();
    expect(
      matchRoute('property', '/platform/payments', configuredHosts.property),
    ).toBeNull();
    expect(
      matchRoute('property', '/property/system/accounts', 'localhost')?.route
        .page,
    ).toBe('accounts');
    expect(matchRoute('platform', '/platform/houses', 'localhost')).toBeNull();
  });
  it('资源详情只接受契约 UUID，支持 v4 和 v7，保留资源标识', () => {
    expect(
      matchRoute('platform', '/companies/' + company, configuredHosts.platform),
    ).toMatchObject({ route: { page: 'company-detail' }, params: { company } });
    expect(
      matchRoute(
        'property',
        '/communities/' + community + '/houses/' + house,
        configuredHosts.property,
      ),
    ).toMatchObject({
      route: { page: 'house-detail' },
      params: { community_id: community, house_id: house },
    });
    for (const invalid of [
      'self',
      'cp-01',
      'undefined',
      '%ZZ',
      '%2F..%2Fcompanies',
    ])
      expect(
        matchRoute(
          'platform',
          '/companies/' + invalid,
          configuredHosts.platform,
        ),
      ).toBeNull();
  });
  it('静态新建导入地址不会误判为批次详情，旧平台接入地址仍可定位', () => {
    expect(
      matchRoute('platform', '/imports/new', configuredHosts.platform)?.route
        .page,
    ).toBe('import-new');
    expect(
      matchRoute('platform', '/platform/property/companies', 'localhost')?.route
        .page,
    ).toBe('companies');
  });
  it('生成路径使用所属后台并保留查询，资源参数不重复放入查询', () => {
    const path = routePath(
      'platform',
      'company-detail',
      { company_id: company, tab: 'admins', back: 'search=锦城&page=2' },
      configuredHosts.platform,
    );
    const url = new URL(path, 'https://admin.example');
    expect(url.pathname).toBe('/companies/' + company);
    expect(url.searchParams.get('tab')).toBe('admins');
    expect(url.searchParams.get('back')).toBe('search=锦城&page=2');
    expect(url.searchParams.has('company_id')).toBe(false);
    expect(
      routePath('property', 'houses', { community_id: community }, 'localhost'),
    ).toBe('/property/communities/' + community + '/houses');
    expect(
      routePath('property', 'accounts', {}, configuredHosts.property),
    ).toBe('/system/accounts');
    expect(() =>
      routePath('platform', 'company-detail', {}, configuredHosts.platform),
    ).toThrow();
  });
});
describe('登录安全回跳', () => {
  it.each([
    'https://evil.example',
    '//evil.example',
    '/\\evil.example',
    '/login',
    '/change-password',
    '/companies/not-a-uuid',
    '/property/payments',
    '/companies#external',
  ])('拒绝外站、身份流程和非本端白名单目标：%s', (candidate) => {
    expect(safeReturn('platform', candidate, configuredHosts.platform)).toBe(
      '/',
    );
  });
  it('保留有效查询与详情路径，本地回跳仍限定本端', () => {
    const target = '/companies/' + company + '?tab=admins&admin_page=2';
    expect(safeReturn('platform', target, configuredHosts.platform)).toBe(
      target,
    );
    expect(safeReturn('property', '/platform/companies', 'localhost')).toBe(
      '/property',
    );
    expect(safeReturn('property', '/property/houses?page=2', 'localhost')).toBe(
      '/property/houses?page=2',
    );
  });
});
