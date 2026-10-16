import { beforeEach, expect, it, vi } from 'vitest';
const state = vi.hoisted(() => ({
  reset: () => {},
  confirm: vi.fn(),
  cancelClaim: vi.fn(),
  releaseBinding: vi.fn(),
  unbindPhone: vi.fn(),
}));
vi.mock('../src/auth/resident', () => ({
  requireSession: () => true,
  onSessionReset: (callback: () => void) => {
    state.reset = callback;
    return () => {};
  },
  listPhones: vi.fn(),
  bindPhone: vi.fn(),
  unbindPhone: state.unbindPhone,
}));
vi.mock('../src/packages/resident/api', () => ({
  cancelClaim: state.cancelClaim,
  releaseBinding: state.releaseBinding,
}));
vi.mock('../src/shared/wechat/ui', async (original) => ({
  ...(await original<object>()),
  confirm: state.confirm,
}));
interface DetailPage {
  data: {
    item: object | null;
    phones: object[];
    busy: boolean;
    loading: boolean;
    error: string;
  };
  setData: (values: object) => void;
  onLoad: (options: object) => void;
  cancel: () => Promise<void>;
  release: () => Promise<void>;
  unbind: (event: object) => Promise<void>;
}
let page: DetailPage;
beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.stubGlobal('wx', {});
  vi.stubGlobal('Page', (definition: DetailPage) => {
    page = definition;
    page.data = structuredClone(definition.data);
    page.setData = (values: object) => Object.assign(page.data, values);
  });
});
it.each(['cancel', 'release', 'unbind'] as const)(
  'discards an old account %s confirmation before sending any write',
  async (action) => {
    if (action === 'cancel')
      await import('../src/packages/resident/pages/claim-detail/index');
    else if (action === 'release')
      await import('../src/packages/resident/pages/house-detail/index');
    else await import('../src/pages/phones/index');
    page.onLoad({ id: 'old-record' });
    Object.assign(page.data, {
      item: { id: 'old-record' },
      phones: [{ id: 'old-record' }],
      loading: false,
    });
    let confirm!: (value: boolean) => void;
    state.confirm.mockImplementation(
      () =>
        new Promise((resolve) => {
          confirm = resolve;
        }),
    );
    const pending =
      action === 'unbind'
        ? page.unbind({ currentTarget: { dataset: { id: 'old-record' } } })
        : page[action]();
    state.reset();
    Object.assign(page.data, {
      item: { id: 'new-record' },
      phones: [{ id: 'new-record' }],
      busy: true,
    });
    confirm(true);
    await pending;
    expect(state.cancelClaim).not.toHaveBeenCalled();
    expect(state.releaseBinding).not.toHaveBeenCalled();
    expect(state.unbindPhone).not.toHaveBeenCalled();
    expect(page.data.busy).toBe(true);
  },
);
