import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { device } from './harness';
const resident = { id: 'resident', type: 'resident', display_name: '居民' };
const extra = {
  id: '01900000-0000-7000-8000-000000000001',
  type: 'test-service',
  display_name: '测试身份甲',
};
const second = {
  ...extra,
  id: '01900000-0000-7000-8000-000000000002',
  display_name: '测试身份乙',
};
function directory(items = [resident]) {
  const api = {
    identities: vi.fn().mockResolvedValue({
      items,
      total: items.length,
      page: 1,
      page_size: 100,
    }),
    identity: vi
      .fn()
      .mockImplementation(async (id: string) =>
        items.find((item) => item.id === id),
      ),
  };
  vi.doMock('../../src/core/account-api', () => api);
  return api;
}
function testEntries() {
  vi.doMock('../../src/ui/business-navigation', () => ({
    entryFor: (type: string) =>
      type === 'resident'
        ? {
            home: '/packages/resident/pages/home/index',
            accepts: (url: string) => url.startsWith('/packages/resident/'),
          }
        : type === 'test-service'
          ? {
              home: '/test/service/index',
              accepts: (url: string) => url === '/test/service/index',
            }
          : undefined,
  }));
}
beforeEach(() => {
  vi.resetModules();
  device();
});
afterEach(() => {
  vi.doUnmock('../../src/core/account-api');
  vi.doUnmock('../../src/ui/business-navigation');
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
it('verifies a sole resident detail before direct entry and keeps the root token', async () => {
  const api = directory();
  const ids = await import('../../src/core/identities');
  const session = await import('../../src/core/session');
  expect(await ids.discoverIdentity()).toEqual(resident);
  expect(api.identity).toHaveBeenCalledExactlyOnceWith('resident');
  expect(ids.currentIdentity()).toEqual(resident);
  expect(session.currentCredential()?.token).toBe('test-token');
});
it('reads the whole directory before deciding whether selection is required', async () => {
  const api = directory([resident, extra]);
  api.identities
    .mockResolvedValueOnce({
      items: [resident],
      total: 2,
      page: 1,
      page_size: 1,
    })
    .mockResolvedValueOnce({ items: [extra], total: 2, page: 2, page_size: 1 });
  const ids = await import('../../src/core/identities');
  expect(await ids.discoverIdentity()).toBeNull();
  expect(api.identities.mock.calls).toEqual([[1], [2]]);
  expect(api.identity).not.toHaveBeenCalled();
});
it.each([
  'page-failure',
  'duplicate',
  'total-change',
  'missing-resident',
  'zero-total',
  'short-page',
])(
  'does not activate a partial or inconsistent directory: %s',
  async (failure) => {
    const api = directory([resident, extra]);
    if (failure === 'missing-resident')
      api.identities.mockResolvedValue({
        items: [extra],
        total: 1,
        page: 1,
        page_size: 100,
      });
    else if (failure === 'zero-total')
      api.identities.mockResolvedValue({
        items: [],
        total: 0,
        page: 1,
        page_size: 100,
      });
    else {
      api.identities.mockResolvedValueOnce({
        items: [resident],
        total: 2,
        page: 1,
        page_size: 1,
      });
      if (failure === 'page-failure')
        api.identities.mockRejectedValueOnce(new Error('network'));
      else
        api.identities.mockResolvedValueOnce({
          items:
            failure === 'short-page'
              ? []
              : failure === 'duplicate'
                ? [resident]
                : [extra],
          total: failure === 'total-change' ? 3 : 2,
          page: 2,
          page_size: 1,
        });
    }
    const ids = await import('../../src/core/identities');
    const session = await import('../../src/core/session');
    await expect(ids.discoverIdentity()).rejects.toThrow();
    expect(ids.currentIdentity()).toBeNull();
    expect(session.currentCredential()?.token).toBe('test-token');
    expect(api.identity).not.toHaveBeenCalled();
  },
);
it('singleflights concurrent full-directory consumers', async () => {
  const api = directory();
  let finish!: (value: unknown) => void;
  api.identities.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const ids = await import('../../src/core/identities');
  const a = ids.loadIdentities();
  const b = ids.loadIdentities();
  expect(a).toBe(b);
  finish({ items: [resident], total: 1, page: 1, page_size: 100 });
  await Promise.all([a, b]);
  expect(api.identities).toHaveBeenCalledOnce();
});
it('unknown types remain visible but cannot select or construct a business path', async () => {
  const api = directory([resident, { ...extra, type: '../../admin' }]);
  const ids = await import('../../src/core/identities');
  expect(await ids.loadIdentities()).toHaveLength(2);
  await expect(ids.selectIdentity(extra.id)).rejects.toMatchObject({
    code: 'client.identity_unsupported',
  });
  expect(api.identity).not.toHaveBeenCalled();
});
it('test-only extra identities switch with one token and fixed registered navigation', async () => {
  testEntries();
  directory([resident, extra, second]);
  const ids = await import('../../src/core/identities');
  const session = await import('../../src/core/session');
  const { wx } = device();
  await ids.loadIdentities();
  await ids.selectIdentity(extra.id);
  const revision = ids.contextRevision();
  await ids.selectIdentity(second.id);
  expect(ids.currentIdentity()?.id).toBe(second.id);
  expect(ids.contextRevision()).toBeGreaterThan(revision);
  expect(session.currentCredential()?.token).toBe('test-token');
  const navigation = await import('../../src/ui/navigation');
  navigation.returnAfterLogin('/packages/resident/pages/home/index');
  expect(wx.reLaunch).toHaveBeenCalledWith({ url: '/test/service/index' });
});
it('only the newest concurrent selection may commit its detail', async () => {
  testEntries();
  const api = directory([resident, extra, second]);
  const finishes = new Map<string, (value: unknown) => void>();
  api.identity.mockImplementation(
    (id: string) =>
      new Promise((resolve) => {
        finishes.set(id, resolve);
      }),
  );
  const ids = await import('../../src/core/identities');
  await ids.loadIdentities();
  const a = ids.selectIdentity(extra.id);
  const b = ids.selectIdentity(second.id);
  finishes.get(second.id)!(second);
  await b;
  finishes.get(extra.id)!(extra);
  await expect(a).rejects.toMatchObject({ name: 'StaleSessionError' });
  expect(ids.currentIdentity()?.id).toBe(second.id);
});
it('a canceled selection cannot activate after its page hides', async () => {
  const api = directory();
  let finish!: (value: unknown) => void;
  api.identity.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const ids = await import('../../src/core/identities');
  await ids.loadIdentities();
  const selecting = ids.selectIdentity('resident');
  ids.cancelIdentitySelection();
  finish(resident);
  await expect(selecting).rejects.toMatchObject({ name: 'StaleSessionError' });
  expect(ids.currentIdentity()).toBeNull();
});
it('a stale detail after session replacement cannot activate an identity', async () => {
  const api = directory();
  let finish!: (value: unknown) => void;
  api.identity.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const ids = await import('../../src/core/identities');
  const session = await import('../../src/core/session');
  await ids.loadIdentities();
  const selecting = ids.selectIdentity('resident');
  session.clearSession();
  finish(resident);
  await expect(selecting).rejects.toMatchObject({ name: 'StaleSessionError' });
  expect(ids.currentIdentity()).toBeNull();
});
it('restores the previous supported choice only after fresh detail verification', async () => {
  testEntries();
  const api = directory([resident, extra]);
  const { storage } = device();
  const { API_BASE_URL } = await import('../../src/config');
  storage.set(
    'ezcmty:' + API_BASE_URL + ':client-identity:resident-a',
    extra.id,
  );
  const ids = await import('../../src/core/identities');
  expect(await ids.discoverIdentity()).toEqual(extra);
  expect(api.identity).toHaveBeenCalledExactlyOnceWith(extra.id);
});
it('separates public requests and discards old business responses after a same-token switch', async () => {
  testEntries();
  directory([resident, extra]);
  const { wx } = device();
  const calls: {
    header: Record<string, string>;
    success(value: unknown): void;
    complete(): void;
  }[] = [];
  const aborts = [vi.fn(), vi.fn()];
  wx.request.mockImplementation((call) => {
    calls.push(call);
    return { abort: aborts[calls.length - 1] };
  });
  const ids = await import('../../src/core/identities');
  const session = await import('../../src/core/session');
  await ids.loadIdentities();
  await ids.selectIdentity('resident');
  const business = ids.businessRequest('/business', {}, 'resident');
  const personal = session.clientRequest('/miniapp-users/me');
  await ids.selectIdentity(extra.id);
  expect(calls[0].header['X-Client-Identity']).toBe('resident');
  expect(calls[1].header['X-Client-Identity']).toBeUndefined();
  calls.forEach((call) => {
    call.success({ statusCode: 200, data: {}, header: {} });
    call.complete();
  });
  await expect(business).rejects.toMatchObject({ name: 'StaleSessionError' });
  await expect(personal).resolves.toEqual({});
  expect(aborts[0]).toHaveBeenCalledOnce();
  expect(aborts[1]).not.toHaveBeenCalled();
  expect(session.currentCredential()?.token).toBe('test-token');
});
it('a same-session business 401 still clears the root token after a context switch', async () => {
  testEntries();
  directory([resident, extra]);
  const { wx } = device();
  let call!: { success(value: unknown): void; complete(): void };
  wx.request.mockImplementation((value) => {
    call = value;
    return { abort: vi.fn() };
  });
  const ids = await import('../../src/core/identities');
  const session = await import('../../src/core/session');
  await ids.loadIdentities();
  await ids.selectIdentity('resident');
  const request = ids.businessRequest('/business', {}, 'resident');
  await ids.selectIdentity(extra.id);
  call.success({
    statusCode: 401,
    data: { code: 'auth.unauthenticated' },
    header: {},
  });
  call.complete();
  await expect(request).rejects.toMatchObject({ status: 401 });
  expect(session.currentCredential()).toBeNull();
});
it.each([
  'client.identity_unavailable',
  'client.identity_mismatch',
  'business.forbidden',
])(
  'handles business rejection without revoking root authentication: %s',
  async (code) => {
    testEntries();
    directory([resident, extra]);
    const { wx } = device();
    wx.request.mockImplementation((call) => {
      call.success({ statusCode: 403, data: { code }, header: {} });
      call.complete();
      return { abort: vi.fn() };
    });
    const ids = await import('../../src/core/identities');
    const session = await import('../../src/core/session');
    await ids.loadIdentities();
    await ids.selectIdentity(extra.id);
    await expect(
      ids.businessRequest('/business', {}, extra.type),
    ).rejects.toMatchObject({ status: 403 });
    expect(session.currentCredential()?.token).toBe('test-token');
    expect(ids.currentIdentity()?.id || null).toBe(
      code === 'client.identity_unavailable' ? null : extra.id,
    );
  },
);
it('passes a root directory 401 through without relabeling it as a context error', async () => {
  const api = directory();
  const { ApiError } = await import('../../src/core/request');
  api.identities.mockRejectedValue(
    new ApiError(401, 'auth.unauthenticated', '请登录'),
  );
  const ids = await import('../../src/core/identities');
  await expect(ids.loadIdentities()).rejects.toMatchObject({ status: 401 });
});
it.each(['directory', 'detail'])(
  'a hidden entry flow cannot reset the active business after its %s returns',
  async (stage) => {
    const api = directory();
    const ids = await import('../../src/core/identities');
    await ids.discoverIdentity();
    const context = ids.contextRevision();
    let visible = true;
    let finish!: (value: unknown) => void;
    if (stage === 'directory')
      api.identities.mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      );
    else
      api.identity.mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      );
    const discovering = ids.discoverIdentity(() => visible);
    if (stage === 'detail') {
      await Promise.resolve();
      await Promise.resolve();
    }
    visible = false;
    finish(
      stage === 'directory'
        ? { items: [resident], total: 1, page: 1, page_size: 100 }
        : resident,
    );
    await expect(discovering).rejects.toMatchObject({
      name: 'StaleSessionError',
    });
    expect(ids.contextRevision()).toBe(context);
    expect(ids.currentIdentity()).toEqual(resident);
  },
);

it.each(['pending', 'committed'])(
  'an older directory cannot clear a newer %s identity selection',
  async (phase) => {
    testEntries();
    const api = directory([resident, extra, second]);
    const ids = await import('../../src/core/identities');
    await ids.loadIdentities();
    await ids.selectIdentity(extra.id);
    let finishDirectory!: (value: unknown) => void;
    let finishDetail!: (value: unknown) => void;
    api.identities.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishDirectory = resolve;
        }),
    );
    api.identity.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishDetail = resolve;
        }),
    );
    const oldDirectory = ids.loadIdentities();
    const choosing = ids.selectIdentity(second.id);
    if (phase === 'committed') {
      finishDetail(second);
      await choosing;
    }
    const context = ids.contextRevision();
    finishDirectory({ items: [resident], total: 1, page: 1, page_size: 100 });
    await oldDirectory;
    expect(ids.contextRevision()).toBe(context);
    expect(ids.currentIdentity()?.id).toBe(
      phase === 'committed' ? second.id : extra.id,
    );
    if (phase === 'pending') {
      finishDetail(second);
      await choosing;
    }
    expect(ids.currentIdentity()?.id).toBe(second.id);
  },
);

it('clears an unchanged active identity when the current directory no longer contains it', async () => {
  testEntries();
  const api = directory([resident, extra]);
  const ids = await import('../../src/core/identities');
  const session = await import('../../src/core/session');
  await ids.loadIdentities();
  await ids.selectIdentity(extra.id);
  const context = ids.contextRevision();
  api.identities.mockResolvedValueOnce({
    items: [resident],
    total: 1,
    page: 1,
    page_size: 100,
  });
  await ids.loadIdentities();
  expect(ids.currentIdentity()).toBeNull();
  expect(ids.contextRevision()).toBeGreaterThan(context);
  expect(session.currentCredential()?.token).toBe('test-token');
});
