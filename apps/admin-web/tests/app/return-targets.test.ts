import { describe, expect, it } from 'vitest';
import { safeReturnTarget } from '@/app/admin-routes';

describe('return-targets', () => {
  it.each([
    'https://evil.test/a',
    '//evil.test/a',
    '/property',
    '/platform/login',
    '/platform/change-password',
    '/platform/unknown',
    '/platform/../property',
  ])('rejects an unsafe return target: %s', (target) => {
    expect(safeReturnTarget('platform_admin', target)).toBe('/platform');
  });
});
