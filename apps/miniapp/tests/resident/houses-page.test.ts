import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Binding } from '../../src/core/types';
const state = vi.hoisted(() => ({
  credential: null as { userId: string } | null,
  revision: 1,
  resets: new Set<() => void>(),
  bindings: vi.fn(),
  go: vi.fn(),
}));
vi.mock('../../src/core/session', () => ({
  currentCredential: () => state.credential,
  sessionRevision: () => state.revision,
  onSessionReset: (listener: () => void) => {
    state.resets.add(listener);
    return () => {
      state.resets.delete(listener);
    };
  },
}));
vi.mock('../../src/core/api', () => ({ bindings: state.bindings }));
vi.mock('../../src/ui/navigation', () => ({
  go: state.go,
  pageUrl: (key: string) => '/packages/resident/pages/' + key + '/index',
}));
type Definition = Record<string, unknown> & { data: Record<string, unknown> };
type Instance = Definition & { setData(values: Record<string, unknown>): void };
let definition: Definition;
async function createPage() {
  await import('../../src/packages/resident/pages/houses/index');
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
  view.invoke('onLoad');
  return view;
}
const binding: Binding = {
  id: 'binding-1',
  house_id: 'house-1',
  community_id: 'community-1',
  claim_application_id: 'claim-1',
  house_label_snapshot: '梧桐里／3栋／1202',
  status: 'active',
  effective_enabled: true,
  granted_at: '2026-10-24T01:00:00Z',
  ended_at: null,
  end_reason: null,
  row_version: 1,
  created_at: '2026-10-24T01:00:00Z',
  updated_at: '2026-10-24T01:00:00Z',
};
beforeEach(() => {
  vi.resetModules();
  vi.resetAllMocks();
  state.credential = null;
  state.revision = 1;
  state.resets.clear();
  state.bindings.mockResolvedValue({
    items: [binding],
    total: 1,
    page: 1,
    page_size: 20,
  });
  vi.stubGlobal('Page', (value: Definition) => {
    definition = value;
  });
});
afterEach(() => vi.unstubAllGlobals());
describe('房屋主页面访客门槛', () => {
  it('未登录留在主页面，不请求本人资源，也不强制导航', async () => {
    const view = await createPage();
    view.invoke('onShow');
    await view.invoke<Promise<void>>('load');
    expect(view.data.signed).toBe(false);
    expect(view.data.loaded).toBe(false);
    expect(view.data.rows).toEqual([]);
    expect(state.bindings).not.toHaveBeenCalled();
    expect(state.go).not.toHaveBeenCalled();
  });
  it('只有用户点击微信登录才导航，并携带房屋主页面返回目标', async () => {
    const view = await createPage();
    view.invoke('onShow');
    view.invoke('signIn');
    expect(state.go).toHaveBeenCalledExactlyOnceWith('login', {
      return_to: '/packages/resident/pages/houses/index',
    });
    expect(state.bindings).not.toHaveBeenCalled();
  });
  it('已登录加载本人房屋，401清理后回到inline gate且不跳转', async () => {
    state.credential = { userId: 'resident-1' };
    const view = await createPage();
    view.invoke('onShow');
    await vi.waitFor(() => expect(view.data.loaded).toBe(true));
    expect(view.data.rows).toHaveLength(1);
    expect(view.data.signed).toBe(true);
    state.credential = null;
    state.revision++;
    state.resets.forEach((listener) => listener());
    expect(view.data.signed).toBe(false);
    expect(view.data.rows).toEqual([]);
    expect(view.data.loaded).toBe(false);
    expect(state.go).not.toHaveBeenCalled();
  });
  it('会话失效后原请求不能把房屋回填到访客页面', async () => {
    let finish!: (value: unknown) => void;
    state.bindings.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    state.credential = { userId: 'resident-1' };
    const view = await createPage();
    view.invoke('onShow');
    state.credential = null;
    state.revision++;
    state.resets.forEach((listener) => listener());
    finish({ items: [binding], total: 1, page: 1, page_size: 20 });
    await Promise.resolve();
    await Promise.resolve();
    expect(view.data.signed).toBe(false);
    expect(view.data.rows).toEqual([]);
    expect(state.go).not.toHaveBeenCalled();
  });
});
