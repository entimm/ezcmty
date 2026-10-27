import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  Binding,
  Claim,
  House,
  PhoneBinding,
} from '../../src/packages/resident/types';
const mocks = vi.hoisted(() => ({
  listPhones: vi.fn(),
  house: vi.fn(),
  bindings: vi.fn(),
  claims: vi.fn(),
  createClaim: vi.fn(),
  requireSession: vi.fn(),
  go: vi.fn(),
  back: vi.fn(),
  redirect: vi.fn(),
  owner: 'resident-a' as string | null,
  revision: 1,
  resets: new Set<() => void>(),
}));
vi.mock('../../src/core/account-api', () => ({ listPhones: mocks.listPhones }));
vi.mock('../../src/packages/resident/api', () => ({
  listPhones: mocks.listPhones,
  house: mocks.house,
  bindings: mocks.bindings,
  claims: mocks.claims,
  createClaim: mocks.createClaim,
}));
vi.mock('../../src/core/session', () => ({
  currentCredential: () => (mocks.owner ? { userId: mocks.owner } : null),
  sessionRevision: () => mocks.revision,
  requireSession: mocks.requireSession,
  onContextReset: (listener: () => void) => {
    mocks.resets.add(listener);
    return () => {
      mocks.resets.delete(listener);
    };
  },
}));
vi.mock('../../src/core/identities', () => ({
  currentCredential: () => (mocks.owner ? { userId: mocks.owner } : null),
  contextRevision: () => mocks.revision,
  requireIdentity: mocks.requireSession,
  onContextReset: (listener: () => void) => {
    mocks.resets.add(listener);
    return () => {
      mocks.resets.delete(listener);
    };
  },
}));
vi.mock('../../src/ui/navigation', () => ({
  go: mocks.go,
  back: mocks.back,
  pageUrl: (key: string, params: Record<string, string> = {}) =>
    key + '?' + new URLSearchParams(params),
}));
type Definition = Record<string, unknown> & { data: Record<string, unknown> };
type Instance = Definition & { setData(values: Record<string, unknown>): void };
let definition: Definition;
const page = <T>(items: T[]) => ({
  items,
  total: items.length,
  page: 1,
  page_size: 20,
});
const house: House = {
  id: 'house-a',
  community_id: 'community-a',
  space_node_id: 'unit-a',
  room_no: '1202',
  display_address: '梧桐里／3栋／1单元／1202',
};
const phone: PhoneBinding = {
  id: 'phone-a',
  phone: '13800136028',
  status: 'active',
  first_verified_at: '2026-10-24T01:00:00Z',
  last_verified_at: '2026-10-24T01:00:00Z',
  unbound_at: null,
  row_version: 1,
  created_at: '2026-10-24T01:00:00Z',
  updated_at: '2026-10-24T01:00:00Z',
};
const claim: Claim = {
  id: 'claim-a',
  community_id: house.community_id,
  house_id: house.id,
  house_label_snapshot: house.display_address,
  applicant_name: '陈雨桐',
  applicant_phone: phone.phone,
  applicant_remark: '本人常住',
  status: 'pending',
  review_reason: null,
  reviewed_at: null,
  cancelled_at: null,
  row_version: 1,
  created_at: '2026-10-24T01:00:00Z',
  updated_at: '2026-10-24T01:00:00Z',
};
async function create(options: Record<string, string> = {}, wait = true) {
  await import('../../src/packages/resident/pages/claim/index');
  const instance = {
    ...definition,
    data: structuredClone(definition.data),
  } as Instance;
  instance.setData = (values) => Object.assign(instance.data, values);
  const view = {
    data: instance.data,
    invoke<T = void>(name: string, ...args: unknown[]): T {
      return (instance[name] as (...values: unknown[]) => T).apply(
        instance,
        args,
      );
    },
  };
  view.invoke('onLoad', options);
  view.invoke('onShow');
  if (wait) await vi.waitFor(() => expect(view.data.loading).toBe(false));
  return view;
}
type View = Awaited<ReturnType<typeof create>>;
function fill(view: View) {
  view.invoke('selectHouse', { detail: { house } });
  view.invoke('nameInput', { detail: { value: ' 陈雨桐 ' } });
  view.invoke('remarkInput', { detail: { value: ' 本人常住 ' } });
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
beforeEach(() => {
  vi.resetModules();
  vi.resetAllMocks();
  mocks.owner = 'resident-a';
  mocks.revision = 1;
  mocks.resets.clear();
  mocks.requireSession.mockReturnValue(true);
  mocks.listPhones.mockResolvedValue(page([phone]));
  mocks.house.mockResolvedValue(house);
  mocks.bindings.mockResolvedValue(page([]));
  mocks.claims.mockResolvedValue(page([]));
  mocks.createClaim.mockResolvedValue(claim);
  vi.stubGlobal('Page', (value: Definition) => {
    definition = value;
  });
  vi.stubGlobal('wx', { redirectTo: mocks.redirect });
});
afterEach(() => vi.unstubAllGlobals());

describe('两步认领资料流程', () => {
  it('首次无房立即打开抽屉，取消后可编辑资料但不能核对，加载完成也不重新弹出', async () => {
    const request = deferred<ReturnType<typeof page<PhoneBinding>>>();
    mocks.listPhones.mockReturnValueOnce(request.promise);
    const view = await create({}, false);
    expect(view.data.picker).toBe(true);
    expect(view.data.title).toBe('填写资料');
    view.invoke('closePicker');
    view.invoke('nameInput', { detail: { value: '陈雨桐' } });
    request.resolve(page([phone]));
    await vi.waitFor(() => expect(view.data.loading).toBe(false));
    expect(view.data.picker).toBe(false);
    expect(view.data.name).toBe('陈雨桐');
    view.invoke('next');
    expect(view.data.step).toBe(1);
    expect(view.data.error).toContain('选择');
    expect(mocks.createClaim).not.toHaveBeenCalled();
  });
  it('点房号直接回资料表单，重新选房取消保留房屋和完整草稿，仅一次next进入最终核对', async () => {
    const view = await create();
    fill(view);
    expect(view.data.step).toBe(1);
    expect(view.data.picker).toBe(false);
    expect(view.data.house).toEqual(house);
    view.invoke('openPicker');
    view.invoke('closePicker');
    expect(view.data.house).toEqual(house);
    expect(view.data.name).toBe(' 陈雨桐 ');
    expect(view.data.phoneId).toBe(phone.id);
    expect(view.data.remark).toBe(' 本人常住 ');
    await view.invoke<Promise<void>>('submit');
    expect(mocks.createClaim).not.toHaveBeenCalled();
    view.invoke('next');
    expect(view.data.step).toBe(2);
    expect(view.data.title).toBe('确认提交');
    expect(view.data.name).toBe('陈雨桐');
    expect(view.data.confirmedPhone).toBe('138 **** 6028');
    view.invoke('leave');
    expect(view.data.step).toBe(1);
    expect(view.data.leaving).toBe(false);
    expect(view.data.house).toEqual(house);
    expect(view.data.remark).toBe('本人常住');
  });
  it('房屋深链直接显示资料表单，不重复弹选房抽屉', async () => {
    const view = await create({
      house_id: house.id,
      community_id: house.community_id,
    });
    expect(mocks.house).toHaveBeenCalledWith(house.community_id, house.id);
    expect(view.data.house).toEqual(house);
    expect(view.data.step).toBe(1);
    expect(view.data.picker).toBe(false);
  });
  it('核对前校验姓名和有效号码，多号码必须明确选，不接受已解绑号码', async () => {
    mocks.listPhones.mockResolvedValue(
      page([
        phone,
        { ...phone, id: 'phone-b', phone: '13900136028' },
        { ...phone, id: 'unbound', status: 'unbound' },
      ]),
    );
    const view = await create();
    view.invoke('selectHouse', { detail: { house } });
    expect(view.data.phoneId).toBe('');
    view.invoke('next');
    expect(view.data.error).toContain('姓名');
    view.invoke('nameInput', { detail: { value: '陈雨桐' } });
    view.invoke('selectPhone', {
      currentTarget: { dataset: { id: 'unbound' } },
    });
    view.invoke('next');
    expect(view.data.step).toBe(1);
    expect(view.data.error).toContain('已验证');
    view.invoke('selectPhone', {
      currentTarget: { dataset: { id: phone.id } },
    });
    view.invoke('next');
    expect(view.data.step).toBe(2);
  });
  it.each(['binding', 'claim'])(
    '存在%s时阻止重复房屋认领，不发提交请求',
    async (kind) => {
      if (kind === 'binding')
        mocks.bindings.mockResolvedValue(
          page([{ house_id: house.id, status: 'active' } as Binding]),
        );
      else mocks.claims.mockResolvedValue(page([claim]));
      const view = await create();
      fill(view);
      view.invoke('next');
      await view.invoke<Promise<void>>('submit');
      expect(view.data.step).toBe(1);
      expect(view.data.house).toBeNull();
      expect(view.data.error).toBeTruthy();
      expect(mocks.createClaim).not.toHaveBeenCalled();
    },
  );
  it('核对后号码失效，回到资料页重新核对，不能沿旧显示提交', async () => {
    const view = await create();
    fill(view);
    view.invoke('next');
    mocks.listPhones.mockResolvedValue(page([{ ...phone, status: 'unbound' }]));
    view.invoke('onHide');
    view.invoke('onShow');
    await vi.waitFor(() => expect(view.data.loading).toBe(false));
    expect(view.data.step).toBe(1);
    expect(view.data.phoneId).toBe('');
    expect(view.data.error).toContain('号码状态');
    expect(mocks.createClaim).not.toHaveBeenCalled();
  });
});

describe('原申请恢复与隔离', () => {
  it('最终核对提交防重复，结果未知保资料并原键恢复，不能返回修改', async () => {
    const { ApiError } = await import('../../src/core/request');
    const request = deferred<Claim>();
    mocks.createClaim
      .mockReturnValueOnce(request.promise)
      .mockResolvedValueOnce(claim);
    const view = await create();
    fill(view);
    view.invoke('next');
    const submitting = view.invoke<Promise<void>>('submit');
    await view.invoke<Promise<void>>('submit');
    expect(mocks.createClaim).toHaveBeenCalledTimes(1);
    request.reject(new ApiError(0, 'network.unknown', '结果未知'));
    await submitting;
    expect(view.data.unknown).toBe(true);
    expect(view.data.name).toBe('陈雨桐');
    view.invoke('previous');
    view.invoke('nameInput', { detail: { value: '其他姓名' } });
    expect(view.data.step).toBe(2);
    expect(view.data.name).toBe('陈雨桐');
    await view.invoke<Promise<void>>('submit');
    expect(mocks.createClaim.mock.calls[1]).toEqual(
      mocks.createClaim.mock.calls[0],
    );
    expect(mocks.redirect).toHaveBeenCalledWith({
      url: 'claim-detail?id=claim-a',
    });
    expect(view.data.name).toBe('');
  });
  it('离开先确认，取消离开保留资料；确认离开才清理', async () => {
    const view = await create();
    fill(view);
    view.invoke('leave');
    expect(view.data.leaving).toBe(true);
    expect(mocks.back).not.toHaveBeenCalled();
    view.invoke('stay');
    expect(view.data.name).toBe(' 陈雨桐 ');
    view.invoke('leave');
    view.invoke('confirmLeave');
    expect(view.data.name).toBe('');
    expect(view.data.house).toBeNull();
    expect(mocks.back).toHaveBeenCalledWith('houses');
  });
  it('隐藏中成功不跳转，回来后展示原申请，避免重新提交', async () => {
    const request = deferred<Claim>();
    mocks.createClaim.mockReturnValueOnce(request.promise);
    const view = await create();
    fill(view);
    view.invoke('next');
    const submitting = view.invoke<Promise<void>>('submit');
    view.invoke('onHide');
    request.resolve(claim);
    await submitting;
    expect(mocks.redirect).not.toHaveBeenCalled();
    view.invoke('onShow');
    expect(mocks.redirect).toHaveBeenCalledWith({
      url: 'claim-detail?id=claim-a',
    });
    expect(mocks.createClaim).toHaveBeenCalledTimes(1);
  });
  it('会话重置立即清草稿，旧提交不能跳转或回填', async () => {
    const request = deferred<Claim>();
    mocks.createClaim.mockReturnValueOnce(request.promise);
    const view = await create();
    fill(view);
    view.invoke('next');
    const submitting = view.invoke<Promise<void>>('submit');
    mocks.owner = null;
    mocks.revision++;
    mocks.resets.forEach((listener) => listener());
    request.resolve(claim);
    await submitting;
    expect(view.data.name).toBe('');
    expect(view.data.house).toBeNull();
    expect(view.data.step).toBe(1);
    expect(mocks.redirect).not.toHaveBeenCalled();
  });
});
