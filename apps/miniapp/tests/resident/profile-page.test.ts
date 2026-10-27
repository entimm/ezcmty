import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({
  credential: { userId: 'resident-a' } as { userId: string } | null,
  revision: 1,
  logout: vi.fn(),
  go: vi.fn(),
}));
vi.mock('../../src/core/account-api', () => ({
  listPhones: async () => ({ items: [], total: 0 }),
}));
vi.mock('../../src/core/session', () => ({
  currentCredential: () => state.credential,
  sessionRevision: () => state.revision,
  logout: state.logout,
}));
vi.mock('../../src/core/identities', () => ({ requireIdentity: () => true }));
vi.mock('../../src/ui/navigation', () => ({ go: state.go }));
vi.mock('../../src/packages/resident/page-state', () => ({
  PageScope: class {
    watch() {}
    enter() {
      return true;
    }
    next() {
      return () => true;
    }
    leave() {}
    dispose() {}
  },
}));
let definition: Record<string, unknown> & { data: Record<string, unknown> };
async function page() {
  await import('../../src/packages/resident/pages/profile/index');
  const view = {
    ...definition,
    data: structuredClone(definition.data),
    setData(value: Record<string, unknown>) {
      Object.assign(this.data, value);
    },
  } as typeof definition & { setData(value: Record<string, unknown>): void };
  const invoke = (name: string) => (view[name] as () => unknown).call(view);
  invoke('onLoad');
  invoke('onShow');
  invoke('exit');
  return { view, invoke };
}
beforeEach(() => {
  vi.resetModules();
  state.credential = { userId: 'resident-a' };
  state.revision = 1;
  state.go.mockReset();
  state.logout.mockReset();
  vi.stubGlobal('Page', (value: typeof definition) => {
    definition = value;
  });
});
afterEach(() => vi.unstubAllGlobals());
it.each([
  'hide-show',
  'new-user',
  'same-user-new-token',
  'new-session-then-401',
])(
  'does not let an old logout navigate or overwrite state after %s',
  async (change) => {
    let finish!: () => void;
    state.logout.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const { view, invoke } = await page();
    const pending = invoke('confirm');
    if (change === 'hide-show') {
      invoke('onHide');
      state.credential = null;
      state.revision++;
      invoke('onShow');
    } else if (change === 'new-session-then-401') {
      state.credential = null;
      state.revision += 3;
    } else {
      state.credential = {
        userId: change === 'new-user' ? 'resident-b' : 'resident-a',
      };
      state.revision++;
    }
    const before = structuredClone(view.data);
    finish();
    await pending;
    expect(state.go).not.toHaveBeenCalled();
    expect(view.data).toEqual(before);
  },
);
it('returns to the anonymous home only for the visible original logout', async () => {
  state.logout.mockImplementation(async () => {
    state.credential = null;
    state.revision++;
  });
  const { invoke } = await page();
  await invoke('confirm');
  expect(state.go).toHaveBeenCalledWith('home');
});
