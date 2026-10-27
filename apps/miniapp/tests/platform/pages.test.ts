import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { PhoneBinding } from '../../src/core/types';
const mocks = vi.hoisted(() => ({
  listPhones: vi.fn(),
  bindPhone: vi.fn(),
  unbindPhone: vi.fn(),
  login: vi.fn(),
  discoverIdentity: vi.fn(),
  restoreSession: vi.fn(),
  revision: 0,
  requireSession: vi.fn(),
  go: vi.fn(),
  back: vi.fn(),
  returnAfterLogin: vi.fn(),
  toast: vi.fn(),
  credential: { value: { userId: 'resident-a' } as { userId: string } | null },
  resets: new Set<() => void>(),
}));
vi.mock('../../src/core/identities', () => ({
  discoverIdentity: mocks.discoverIdentity,
}));
vi.mock('../../src/core/account-api', () => ({
  listPhones: mocks.listPhones,
  bindPhone: mocks.bindPhone,
  unbindPhone: mocks.unbindPhone,
}));
vi.mock('../../src/core/session', () => ({
  currentCredential: () => mocks.credential.value,
  requireSession: mocks.requireSession,
  login: mocks.login,
  restoreSession: mocks.restoreSession,
  sessionRevision: () => mocks.revision,
  safeReturn: (value: string | undefined) =>
    value || '/packages/resident/pages/home/index',
  onSessionReset: (listener: () => void) => {
    mocks.resets.add(listener);
    return () => {
      mocks.resets.delete(listener);
    };
  },
}));
vi.mock('../../src/ui/navigation', () => ({
  go: mocks.go,
  back: mocks.back,
  returnAfterLogin: mocks.returnAfterLogin,
  paths: { phones: '/pages/phones/index' },
}));
type Definition = Record<string, unknown> & { data: Record<string, unknown> };
type Instance = Definition & { setData(values: Record<string, unknown>): void };
let definition: Definition;
function page() {
  const instance = {
    ...definition,
    data: structuredClone(definition.data),
  } as Instance;
  instance.setData = (values) => Object.assign(instance.data, values);
  return {
    data: instance.data,
    invoke<T = void>(name: string, ...args: unknown[]): T {
      return (instance[name] as (...values: unknown[]) => T).apply(
        instance,
        args,
      );
    },
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
const phone: PhoneBinding = {
  id: 'phone-a',
  phone: '13800136028',
  status: 'active',
  first_verified_at: '2026-10-24T02:00:00Z',
  last_verified_at: '2026-10-24T02:00:00Z',
  unbound_at: null,
  row_version: 1,
  created_at: '2026-10-24T02:00:00Z',
  updated_at: '2026-10-24T02:00:00Z',
};
const phonePage = (items = [phone], total = items.length, page = 1) => ({
  items,
  total,
  page,
  page_size: 20,
});
async function shownPhonePage() {
  await import('../../src/pages/phones/index');
  const view = page();
  view.invoke('onLoad', {});
  view.invoke('onShow');
  await vi.waitFor(() => expect(view.data.loading).toBe(false));
  return view;
}
beforeEach(() => {
  vi.resetModules();
  vi.resetAllMocks();
  mocks.resets.clear();
  mocks.revision = 0;
  mocks.restoreSession.mockResolvedValue({});
  mocks.credential.value = { userId: 'resident-a' };
  mocks.requireSession.mockReturnValue(true);
  mocks.listPhones.mockResolvedValue(phonePage());
  mocks.discoverIdentity.mockResolvedValue({
    id: 'resident',
    type: 'resident',
    display_name: '居民',
  });
  vi.stubGlobal('Page', (value: Definition) => {
    definition = value;
  });
  vi.stubGlobal('wx', { showToast: mocks.toast, stopPullDownRefresh: vi.fn() });
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe('手机号页面原验证和生命周期', () => {
  it('页面隐藏后列表响应不回填', async () => {
    const request = deferred<ReturnType<typeof phonePage>>();
    mocks.listPhones.mockReturnValue(request.promise);
    await import('../../src/pages/phones/index');
    const view = page();
    view.invoke('onLoad', {});
    view.invoke('onShow');
    view.invoke('onHide');
    request.resolve(phonePage());
    await request.promise;
    await Promise.resolve();
    expect(view.data.phones).toEqual([]);
    expect(view.data.loading).toBe(false);
  });
  it('隐藏中验证成功不会Toast或改表单，回来后显示可信列表并清已验证输入', async () => {
    const view = await shownPhonePage();
    const request = deferred<PhoneBinding>();
    mocks.bindPhone.mockReturnValue(request.promise);
    view.invoke('input', { detail: { value: '13800136028' } });
    const submitting = view.invoke<Promise<void>>('authorize', {
      detail: { code: 'wechat-code' },
    });
    view.invoke('onHide');
    request.resolve(phone);
    await submitting;
    expect(view.data.input).toBe('13800136028');
    expect(mocks.toast).not.toHaveBeenCalled();
    view.invoke('onShow');
    await vi.waitFor(() => expect(view.data.loading).toBe(false));
    expect(view.data.input).toBe('');
    expect(view.data.busy).toBe(false);
    expect(view.data.phones).toHaveLength(1);
  });
  it('隐藏期间未知结果保留原code/key/输入，显示后恢复而不重建验证', async () => {
    const { ApiError } = await import('../../src/core/request');
    const view = await shownPhonePage();
    const request = deferred<PhoneBinding>();
    mocks.bindPhone
      .mockReturnValueOnce(request.promise)
      .mockResolvedValueOnce(phone);
    view.invoke('input', { detail: { value: '13800136028' } });
    const submitting = view.invoke<Promise<void>>('authorize', {
      detail: { code: 'once-only-code' },
    });
    view.invoke('onHide');
    request.reject(new ApiError(0, 'network.unknown', '结果未知'));
    await submitting;
    expect(view.data.pending).toBe(false);
    expect(mocks.toast).not.toHaveBeenCalled();
    view.invoke('onShow');
    await vi.waitFor(() => expect(view.data.loading).toBe(false));
    expect(view.data.pending).toBe(true);
    expect(view.data.busy).toBe(false);
    expect(view.data.input).toBe('13800136028');
    await view.invoke<Promise<void>>('retryVerification');
    await vi.waitFor(() => expect(view.data.busy).toBe(false));
    expect(mocks.bindPhone).toHaveBeenCalledTimes(2);
    expect(mocks.bindPhone.mock.calls[1]).toEqual(
      mocks.bindPhone.mock.calls[0],
    );
    expect(view.data.pending).toBe(false);
  });
  it('显示回来的进行中验证保持busy，结束后解除，不会卡死', async () => {
    const view = await shownPhonePage();
    const request = deferred<PhoneBinding>();
    mocks.bindPhone.mockReturnValue(request.promise);
    const submitting = view.invoke<Promise<void>>('authorize', {
      detail: { code: 'code' },
    });
    view.invoke('onHide');
    view.invoke('onShow');
    expect(view.data.busy).toBe(true);
    request.resolve(phone);
    await submitting;
    await vi.waitFor(() => expect(view.data.busy).toBe(false));
  });
  it('用户取消微信授权保留输入，不发业务请求', async () => {
    const view = await shownPhonePage();
    view.invoke('input', { detail: { value: '13800136028' } });
    await view.invoke<Promise<void>>('authorize', { detail: {} });
    expect(view.data.input).toBe('13800136028');
    expect(view.data.verifyError).toContain('已取消');
    expect(mocks.bindPhone).not.toHaveBeenCalled();
  });
  it('解绑冲突反馈不会被刷新清掉', async () => {
    const { ApiError } = await import('../../src/core/request');
    const view = await shownPhonePage();
    mocks.unbindPhone.mockRejectedValue(
      new ApiError(409, 'phone.changed', '号码状态已变化，请重新查看'),
    );
    view.invoke('openRemove', { currentTarget: { dataset: { id: phone.id } } });
    await view.invoke<Promise<void>>('confirmRemove');
    await vi.waitFor(() => expect(view.data.loading).toBe(false));
    expect(view.data.removeError).toContain('状态已变化');
    expect(view.data.busy).toBe(false);
    expect(view.data.phones).toHaveLength(1);
  });
  it.each([403, 404])(
    '权威拒绝%s后清空旧号码与历史，不能继续显示旧数据',
    async (status) => {
      const { ApiError } = await import('../../src/core/request');
      const view = await shownPhonePage();
      mocks.listPhones.mockRejectedValueOnce(
        new ApiError(status, 'phone.forbidden', '不可读取'),
      );
      await view.invoke<Promise<void>>('load');
      expect(view.data.phones).toEqual([]);
      expect(view.data.history).toEqual([]);
      expect(view.data.hasMore).toBe(false);
      expect(view.data.error).toBeTruthy();
    },
  );
  it('普通加载更多失败保留已显示号码与分页位置', async () => {
    mocks.listPhones.mockResolvedValueOnce(phonePage([phone], 21));
    const view = await shownPhonePage();
    mocks.listPhones.mockRejectedValueOnce(new Error('网络暂时中断'));
    await view.invoke<Promise<void>>('load', true);
    expect(view.data.phones).toHaveLength(1);
    expect(view.data.page).toBe(1);
    expect(view.data.moreError).toContain('网络');
  });
  it('会话失效立即清理号码与填写资料', async () => {
    const view = await shownPhonePage();
    view.invoke('input', { detail: { value: '13800136028' } });
    mocks.credential.value = null;
    mocks.resets.forEach((listener) => listener());
    expect(view.data.input).toBe('');
    expect(view.data.phones).toEqual([]);
    expect(view.data.signed).toBe(false);
    expect(view.data.busy).toBe(false);
  });
});

describe('登录页返回目标与后台响应', () => {
  it.each(['return_to', 'returnTo'])('兼容%s返回参数', async (key) => {
    await import('../../src/pages/login/index');
    const view = page();
    const target = '/packages/resident/pages/claim/index';
    view.invoke('onLoad', { [key]: target });
    mocks.credential.value = null;
    view.invoke('onShow');
    mocks.login.mockImplementation(async () => {
      mocks.credential.value = { userId: 'resident-a' };
      mocks.revision++;
    });
    await view.invoke<Promise<void>>('signIn');
    expect(mocks.returnAfterLogin).toHaveBeenLastCalledWith(target);
  });
  it('隐藏中完成登录不会强制跳转，回来后继续允许的目标', async () => {
    await import('../../src/pages/login/index');
    const view = page();
    const target = '/packages/resident/pages/claim/index';
    const request = deferred<void>();
    mocks.credential.value = null;
    mocks.login.mockReturnValue(request.promise);
    view.invoke('onLoad', { return_to: target });
    view.invoke('onShow');
    const signing = view.invoke<Promise<void>>('signIn');
    view.invoke('onHide');
    mocks.credential.value = { userId: 'resident-a' };
    request.resolve();
    await signing;
    expect(mocks.returnAfterLogin).not.toHaveBeenCalled();
    view.invoke('onShow');
    await vi.waitFor(() =>
      expect(mocks.returnAfterLogin).toHaveBeenCalledWith(target),
    );
    expect(view.data.busy).toBe(false);
  });
  it('隐藏后重新显示的进行中登录不会卡busy或重复发登录请求', async () => {
    await import('../../src/pages/login/index');
    const view = page();
    const request = deferred<void>();
    mocks.credential.value = null;
    mocks.login.mockReturnValue(request.promise);
    view.invoke('onLoad', {});
    view.invoke('onShow');
    const signing = view.invoke<Promise<void>>('signIn');
    view.invoke('onHide');
    view.invoke('onShow');
    expect(view.data.busy).toBe(true);
    await view.invoke<Promise<void>>('signIn');
    request.resolve();
    await signing;
    expect(mocks.login).toHaveBeenCalledTimes(1);
    expect(view.data.busy).toBe(false);
  });
});

it('目录异常仍保留已认证用户的公共手机号入口', async () => {
  mocks.discoverIdentity.mockRejectedValue(new Error('身份目录不完整'));
  await import('../../src/pages/index/index');
  const view = page();
  await view.invoke<Promise<void>>('restore');
  expect(view.data.signed).toBe(true);
  expect(view.data.error).toBe('身份目录不完整');
  expect(mocks.credential.value).not.toBeNull();
  view.invoke('phones');
  expect(mocks.go).toHaveBeenCalledWith('phones');
});
