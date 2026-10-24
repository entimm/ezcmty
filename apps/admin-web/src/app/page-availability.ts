import type { Scope } from '../shared/types';

// 页面开放控制独立于业务权限；恢复时将对应值改为 true 并重新构建发布。
export const propertyPageAvailability: Record<string, boolean> = {
  communities: false,
  'payment-configuration': false,
};

export function isPageAvailable(scope: Scope, page: string) {
  return scope !== 'property' || propertyPageAvailability[page] !== false;
}
