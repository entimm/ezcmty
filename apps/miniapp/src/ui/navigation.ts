import { currentIdentity } from '../core/identities';
import { entryFor } from './business-navigation';
import { safeReturn } from '../core/session';
export const paths = {
  index: '/pages/index/index',
  login: '/pages/login/index',
  phones: '/pages/phones/index',
  identities: '/pages/identities/index',
  home: '/packages/resident/pages/home/index',
  bills: '/packages/resident/pages/bills/index',
  houses: '/packages/resident/pages/houses/index',
  profile: '/packages/resident/pages/profile/index',
  'house-detail': '/packages/resident/pages/house-detail/index',
  claim: '/packages/resident/pages/claim/index',
  claims: '/packages/resident/pages/claims/index',
  'claim-detail': '/packages/resident/pages/claim-detail/index',
  'bill-detail': '/packages/resident/pages/bill-detail/index',
  'payment-confirm': '/packages/resident/pages/payment-confirm/index',
  'payment-orders': '/packages/resident/pages/payment-orders/index',
  'payment-detail': '/packages/resident/pages/payment-detail/index',
} as const;
export type PageKey = keyof typeof paths;
const roots = new Set(['home', 'bills', 'houses', 'profile']);
export function pageUrl(
  page: string,
  params: Record<string, string> = {},
): string {
  const path = paths[page as PageKey];
  if (!path) return paths.home;
  const query = Object.entries(params)
    .map(
      ([key, value]) =>
        encodeURIComponent(key) + '=' + encodeURIComponent(value),
    )
    .join('&');
  return path + (query ? '?' + query : '');
}
export function safeReturnTo(value: string | undefined): string {
  return safeReturn(value);
}
export function go(page: string, params: Record<string, string> = {}): void {
  const url = pageUrl(page, params);
  if (roots.has(page)) wx.reLaunch({ url });
  else wx.navigateTo({ url, fail: () => wx.redirectTo({ url }) });
}
export function returnAfterLogin(url: string): void {
  const target = safeReturnTo(url);
  const selected = currentIdentity();
  const entry = selected && entryFor(selected.type);
  wx.reLaunch({
    url:
      target === paths.phones
        ? target
        : entry
          ? entry.accepts(target)
            ? target
            : entry.home
          : paths.identities,
  });
}
export function back(fallback = 'home'): void {
  if (getCurrentPages().length > 1)
    wx.navigateBack({ fail: () => go(fallback) });
  else go(fallback);
}
