import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  Binding,
  Community,
  House,
  SpaceNode,
} from '../../src/core/types';
const mocks = vi.hoisted(() => ({
  communities: vi.fn(),
  nodes: vi.fn(),
  houses: vi.fn(),
  owner: 'resident-a' as string | null,
  revision: 1,
  resets: new Set<() => void>(),
}));
vi.mock('../../src/core/api', () => ({
  communities: mocks.communities,
  nodes: mocks.nodes,
  houses: mocks.houses,
}));
vi.mock('../../src/core/session', () => ({
  currentCredential: () => (mocks.owner ? { userId: mocks.owner } : null),
  sessionRevision: () => mocks.revision,
  onSessionReset: (listener: () => void) => {
    mocks.resets.add(listener);
    return () => {
      mocks.resets.delete(listener);
    };
  },
}));
type Handler = (...values: unknown[]) => unknown;
type Definition = {
  data: Record<string, unknown>;
  properties: Record<string, { value: unknown }>;
  methods: Record<string, Handler>;
  observers: Record<string, Handler>;
  lifetimes: Record<string, Handler>;
};
type Instance = Record<string, unknown> & {
  data: Record<string, unknown>;
  setData(values: Record<string, unknown>): void;
  triggerEvent(name: string, detail?: Record<string, unknown>): void;
};
let definition: Definition;
async function picker(properties: Record<string, unknown> = {}) {
  await import('../../src/packages/resident/components/house-picker/index');
  const defaults = Object.fromEntries(
    Object.entries(definition.properties).map(([key, value]) => [
      key,
      value.value,
    ]),
  );
  const events: { name: string; detail?: Record<string, unknown> }[] = [];
  let committed: Record<string, unknown> | null = null;
  const instance: Instance = {
    ...definition.methods,
    data: {
      ...structuredClone(definition.data),
      ...defaults,
      ...properties,
      open: true,
    },
    setData() {},
    triggerEvent() {},
  };
  instance.setData = (values) => Object.assign(instance.data, values);
  instance.triggerEvent = (name, detail) => {
    events.push({ name, detail });
    if (name === 'confirm') committed = detail || {};
    // A parent closes the layer without applying its temporary selection.
    if (name === 'close') {
      instance.data.open = false;
      definition.observers.open.call(instance, false);
    }
  };
  const invoke = <T = void>(name: string, ...args: unknown[]): T =>
    (instance[name] as (...values: unknown[]) => T).apply(instance, args);
  definition.lifetimes.attached.call(instance);
  invoke('initialize');
  return {
    data: instance.data,
    events,
    invoke,
    committed: () => committed,
    reopen() {
      instance.data.open = true;
      definition.observers.open.call(instance, true);
    },
    changeProperties(values: Record<string, unknown>) {
      Object.assign(instance.data, values);
    },
    detach() {
      definition.lifetimes.detached.call(instance);
    },
  };
}
const community: Community = {
  id: 'community-1',
  name: '云栖花园',
  address: '清溪路16号',
};
const building: SpaceNode = {
  id: 'building-1',
  community_id: community.id,
  parent_id: null,
  name: '2栋',
  node_type: 'building',
  has_children: true,
};
const unit: SpaceNode = {
  id: 'unit-1',
  community_id: community.id,
  parent_id: building.id,
  name: '1单元',
  node_type: 'unit',
  has_children: false,
};
const directHouse: House = {
  id: 'house-direct',
  community_id: community.id,
  space_node_id: building.id,
  room_no: '101',
  display_address: '云栖花园／2栋／101',
};
const unitHouse: House = {
  id: 'house-unit',
  community_id: community.id,
  space_node_id: unit.id,
  room_no: '201',
  display_address: '云栖花园／2栋／1单元／201',
};
const binding = (id: string, changes: Partial<Binding> = {}): Binding => ({
  id,
  community_id: community.id,
  house_id: 'house-' + id,
  claim_application_id: 'claim-' + id,
  house_label_snapshot: '云栖花园／2栋／101',
  status: 'active',
  effective_enabled: true,
  granted_at: '2026-10-24T01:00:00Z',
  ended_at: null,
  end_reason: null,
  row_version: 1,
  created_at: '2026-10-24T01:00:00Z',
  updated_at: '2026-10-24T01:00:00Z',
  ...changes,
});
const page = <T>(items: T[]) => ({
  items,
  total: items.length,
  page: 1,
  page_size: 20,
});
const tap = (id: string) => ({ currentTarget: { dataset: { id } } });
async function settled(view: Awaited<ReturnType<typeof picker>>) {
  await vi.waitFor(() => expect(view.data.loading).toBe(false));
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}
beforeEach(() => {
  vi.resetModules();
  vi.resetAllMocks();
  mocks.owner = 'resident-a';
  mocks.revision = 1;
  mocks.resets.clear();
  vi.stubGlobal('Component', (value: Definition) => {
    definition = value;
  });
  vi.stubGlobal('wx', {
    getWindowInfo: () => ({ windowHeight: 780 }),
    showToast: vi.fn(),
  });
  mocks.communities.mockResolvedValue(page([community]));
  mocks.nodes.mockImplementation(
    async (_communityId: string, parentId?: string) =>
      page(
        parentId === building.id
          ? [unit]
          : parentId === unit.id
            ? []
            : [building],
      ),
  );
  mocks.houses.mockImplementation(
    async (_communityId: string, spaceId: string) =>
      page(spaceId === building.id ? [directHouse] : [unitHouse]),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe('房屋抽屉选择与确认', () => {
  it('省略分区，社区→楼栋→单元→房号点击后直接提交完整选择', async () => {
    const view = await picker({ selectedId: 'previous-house' });
    await settled(view);
    view.invoke('chooseCommunity', tap(community.id));
    await settled(view);
    view.invoke('chooseNode', tap(building.id));
    await settled(view);
    // A building may expose child spaces and direct rooms at the same time.
    expect((view.data.nodes as SpaceNode[]).map((row) => row.id)).toEqual([
      unit.id,
    ]);
    expect((view.data.houses as House[]).map((row) => row.id)).toEqual([
      directHouse.id,
    ]);
    view.invoke('chooseNode', tap(unit.id));
    await settled(view);
    view.invoke('chooseHouse', tap(unitHouse.id));
    expect(view.data.selectedId).toBe('previous-house');
    expect(view.committed()).toEqual({
      house: unitHouse,
      community,
      path: [building, unit],
    });
    view.invoke('chooseHouse', tap(unitHouse.id));
    expect(view.events.map((event) => event.name)).toEqual(['confirm']);
    expect(mocks.houses).toHaveBeenCalledWith(community.id, unit.id, '', 1);
    view.detach();
  });
  it('返回和关闭只取消未选路径，重新打开后点击直连房号立即选择', async () => {
    const view = await picker({ selectedId: 'previous-house' });
    await settled(view);
    view.invoke('chooseCommunity', tap(community.id));
    await settled(view);
    view.invoke('chooseNode', tap(building.id));
    await settled(view);
    view.invoke('back');
    await settled(view);
    expect(view.data.path).toEqual([]);
    expect(view.committed()).toBeNull();
    expect(view.data.selectedId).toBe('previous-house');
    view.invoke('close');
    expect(view.committed()).toBeNull();
    expect(view.events.map((event) => event.name)).toEqual(['close']);
    expect(view.data.selectedId).toBe('previous-house');
    view.reopen();
    await settled(view);
    expect(view.data.path).toEqual([]);
    expect(view.committed()).toBeNull();
    view.invoke('chooseCommunity', tap(community.id));
    await settled(view);
    view.invoke('chooseNode', tap(building.id));
    await settled(view);
    view.invoke('chooseHouse', tap(directHouse.id));
    expect(view.committed()).toEqual({
      house: directHouse,
      community,
      path: [building],
    });
    view.detach();
  });
  it.each(['未知房号', '其他小区房屋', '其他空间房屋'])(
    '拒绝非法选择：%s',
    async (kind) => {
      const view = await picker();
      await settled(view);
      view.invoke('chooseCommunity', tap(community.id));
      await settled(view);
      view.invoke('chooseNode', tap(building.id));
      await settled(view);
      if (kind === '其他小区房屋')
        view.changeProperties({
          houses: [{ ...directHouse, community_id: 'other-community' }],
        });
      if (kind === '其他空间房屋')
        view.changeProperties({
          houses: [{ ...directHouse, space_node_id: 'other-space' }],
        });
      view.invoke(
        'chooseHouse',
        tap(kind === '未知房号' ? 'unknown-house' : directHouse.id),
      );
      expect(view.events).toEqual([]);
      expect(view.committed()).toBeNull();
      view.detach();
    },
  );
  it.each([
    '抽屉已关闭',
    '列表正在刷新',
    '列表读取失败',
    '会话版本已变',
    '居民已退出',
  ])('拒绝失效选择：%s', async (kind) => {
    const view = await picker();
    await settled(view);
    view.invoke('chooseCommunity', tap(community.id));
    await settled(view);
    view.invoke('chooseNode', tap(building.id));
    await settled(view);
    if (kind === '抽屉已关闭') view.changeProperties({ open: false });
    if (kind === '列表正在刷新') view.changeProperties({ loading: true });
    if (kind === '列表读取失败') view.changeProperties({ error: '加载失败' });
    if (kind === '会话版本已变') mocks.revision++;
    if (kind === '居民已退出') mocks.owner = null;
    view.invoke('chooseHouse', tap(directHouse.id));
    expect(view.events).toEqual([]);
    expect(view.committed()).toBeNull();
    view.detach();
  });
  it('switch过滤历史和停用授权，即使调用confirm也不能确认无效房屋', async () => {
    const active = binding('active');
    const disabled = binding('disabled', { effective_enabled: false });
    const released = binding('released', { status: 'released' });
    const revoked = binding('revoked', { status: 'revoked' });
    const view = await picker({
      mode: 'switch',
      selectedId: released.id,
      bindings: [active, disabled, released, revoked],
    });
    expect((view.data.bindingRows as Binding[]).map((row) => row.id)).toEqual([
      active.id,
    ]);
    expect(mocks.communities).not.toHaveBeenCalled();
    view.invoke('confirm');
    view.invoke('chooseBinding', tap(disabled.id));
    view.invoke('confirm');
    expect(view.committed()).toBeNull();
    view.invoke('chooseBinding', tap(active.id));
    expect(view.committed()).toBeNull();
    view.invoke('confirm');
    expect(view.committed()).toEqual({ binding: active });
    view.detach();
  });
  it('switch确认时重新检查父级传入授权，不能确认选择后已撤销的房屋', async () => {
    const active = binding('active');
    const view = await picker({
      mode: 'switch',
      selectedId: active.id,
      bindings: [active],
    });
    view.invoke('chooseBinding', tap(active.id));
    view.changeProperties({ bindings: [{ ...active, status: 'revoked' }] });
    view.invoke('confirm');
    expect(view.committed()).toBeNull();
    expect(view.events).toEqual([]);
    view.detach();
  });
});

describe('房屋抽屉异步隔离', () => {
  it('较早搜索的迟到结果不能覆盖最近结果', async () => {
    const old = deferred<ReturnType<typeof page<Community>>>();
    mocks.communities.mockReturnValueOnce(old.promise);
    const latest = { ...community, id: 'community-latest', name: '美好家园' };
    mocks.communities.mockResolvedValueOnce(page([latest]));
    const view = await picker();
    view.invoke('onSearch', { detail: { value: '美好' } });
    await view.invoke<Promise<void>>('load');
    old.resolve(page([community]));
    await old.promise;
    await Promise.resolve();
    expect((view.data.communities as Community[]).map((row) => row.id)).toEqual(
      [latest.id],
    );
    expect(view.committed()).toBeNull();
    view.detach();
  });
  it('关闭后迟到结果不回填，正式选择不变', async () => {
    const request = deferred<ReturnType<typeof page<Community>>>();
    mocks.communities.mockReturnValueOnce(request.promise);
    const view = await picker({ selectedId: 'previous-house' });
    view.invoke('close');
    request.resolve(page([community]));
    await request.promise;
    await Promise.resolve();
    expect(view.data.communities).toEqual([]);
    expect(view.data.selectedId).toBe('previous-house');
    expect(view.committed()).toBeNull();
    view.detach();
  });
  it('会话重置清除临时信息并通知关闭，原请求不能再次回填', async () => {
    const request = deferred<ReturnType<typeof page<Community>>>();
    mocks.communities.mockReturnValueOnce(request.promise);
    const view = await picker();
    mocks.owner = null;
    mocks.revision++;
    mocks.resets.forEach((listener) => listener());
    request.resolve(page([community]));
    await request.promise;
    await Promise.resolve();
    expect(view.events.map((event) => event.name)).toEqual(['close']);
    expect(view.data.open).toBe(false);
    expect(view.data.communities).toEqual([]);
    expect(view.data.community).toBeNull();
    expect(view.data.path).toEqual([]);
    expect(view.data.houses).toEqual([]);
    expect(view.committed()).toBeNull();
    view.detach();
    expect(mocks.resets.size).toBe(0);
  });
  it('相同居民重新登录后的旧会话响应同样失效', async () => {
    const request = deferred<ReturnType<typeof page<Community>>>();
    mocks.communities.mockReturnValueOnce(request.promise);
    const view = await picker();
    mocks.revision++;
    request.resolve(page([community]));
    await request.promise;
    await Promise.resolve();
    expect(view.data.communities).toEqual([]);
    expect(view.committed()).toBeNull();
    view.detach();
  });
});
