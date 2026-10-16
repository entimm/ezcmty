import { expect, it } from 'vitest';
import { safeReturn, residentHome } from '../src/shared/wechat/ui';
it.each([
  'https://other.example',
  '//other',
  '/pages/admin/index',
  '/packages/merchant/pages/home/index',
  '/packages/resident/pages/claim/index?phone=13800138000',
  '%E0%A4%A',
])('rejects unsupported return destination %s', (value) => {
  expect(safeReturn(value)).toBe(residentHome);
});
it('restores an allowed house claim destination with identifiers only', () => {
  const url =
    '/packages/resident/pages/claim/index?house_id=019a0000-0000-7000-8000-000000000001&community_id=019a0000-0000-7000-8000-000000000002';
  expect(safeReturn(encodeURIComponent(url))).toBe(url);
});
