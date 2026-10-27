vi.mock('../../src/core/identities', () => ({
  currentIdentity: () => ({
    id: 'resident',
    type: 'resident',
    display_name: '居民',
  }),
}));
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
  back,
  go,
  pageUrl,
  paths,
  returnAfterLogin,
} from '../../src/ui/navigation';

const native = {
  reLaunch: vi.fn(),
  navigateTo: vi.fn(),
  redirectTo: vi.fn(),
  navigateBack: vi.fn(),
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('wx', native);
  vi.stubGlobal('getCurrentPages', () => []);
});
afterEach(() => vi.unstubAllGlobals());

it.each(['home', 'bills', 'houses', 'profile'])(
  '主入口 %s 替换栈而不堆积返回历史',
  (page) => {
    go(page);
    expect(native.reLaunch).toHaveBeenCalledWith({ url: pageUrl(page) });
    expect(native.navigateTo).not.toHaveBeenCalled();
  },
);

it('详情保留返回栈并安全编码资源 ID', () => {
  go('bill-detail', { id: 'a/b?c' });
  expect(native.navigateTo).toHaveBeenCalledWith(
    expect.objectContaining({ url: paths['bill-detail'] + '?id=a%2Fb%3Fc' }),
  );
  expect(native.reLaunch).not.toHaveBeenCalled();
});

it('外部地址和含敏感字段的登录回跳回到首页', () => {
  returnAfterLogin('https://other.invalid/private');
  returnAfterLogin(paths.claim + '?phone=13800000000');
  returnAfterLogin('%E0%A4%A');
  expect(native.reLaunch.mock.calls).toEqual([
    [{ url: paths.home }],
    [{ url: paths.home }],
    [{ url: paths.home }],
  ]);
});

it('登录后只恢复白名单页面和受约束的资源参数', () => {
  const target =
    paths['payment-detail'] + '?id=01900000-0000-7000-8000-000000000001';
  returnAfterLogin(encodeURIComponent(target));
  expect(native.reLaunch).toHaveBeenCalledWith({ url: target });
});

it('没有上一页时返回首页，有上一页时使用原生返回', () => {
  back();
  expect(native.reLaunch).toHaveBeenCalledWith({ url: paths.home });
  vi.stubGlobal('getCurrentPages', () => [{}, {}]);
  back();
  expect(native.navigateBack).toHaveBeenCalledTimes(1);
});
