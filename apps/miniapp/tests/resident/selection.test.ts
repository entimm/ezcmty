import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { device } from '../core/harness';

beforeEach(() => {
  vi.resetModules();
});
afterEach(() => {
  vi.doUnmock('../../src/config');
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it.each([
  ['https://resident-a.example.invalid', 'https://resident-b.example.invalid'],
  ['https://resident-b.example.invalid', 'https://resident-a.example.invalid'],
])(
  'keeps resident house selection within environment %s and its user',
  async (environment, otherEnvironment) => {
    const { storage } = device();
    vi.doMock('../../src/config', () => ({ API_BASE_URL: environment }));
    storage.set('xlife:' + environment + ':resident-session', {
      token: 'token-a',
      userId: 'resident-a',
      expiresAt: '2030-01-01T00:00:00Z',
    });
    const ownKey = 'xlife:' + environment + ':resident-house:resident-a';
    const others = new Map([
      ['xlife:' + environment + ':resident-house:resident-b', 'binding-b'],
      [
        'xlife:' + otherEnvironment + ':resident-house:resident-a',
        'binding-other-environment',
      ],
      [
        'xlife:' + environment + ':property-house:resident-a',
        'binding-property',
      ],
      [
        'xlife:' + environment + ':merchant-house:resident-a',
        'binding-merchant',
      ],
    ]);
    storage.set(ownKey, 'binding-a');
    others.forEach((value, key) => storage.set(key, value));
    const selection = await import('../../src/packages/resident/selection');

    expect(selection.getSelectedBindingId()).toBe('binding-a');
    selection.setSelectedBindingId('binding-updated');
    expect(storage.get(ownKey)).toBe('binding-updated');
    expect(new Map([...storage].filter(([key]) => others.has(key)))).toEqual(
      others,
    );
  },
);

it('clears the old selection on login as another user and only clears that user on logout', async () => {
  const { wx, storage } = device();
  const { API_BASE_URL } = await import('../../src/config');
  const selection = await import('../../src/packages/resident/selection');
  const session = await import('../../src/core/session');
  const prefix = 'xlife:' + API_BASE_URL;
  const otherScopeKey = prefix + ':property-house:resident-b';
  storage.set(prefix + ':resident-house:resident-b', 'binding-b');
  storage.set(otherScopeKey, 'property-binding-b');
  selection.setSelectedBindingId('binding-a');
  wx.login.mockImplementation(
    (options: { success: (result: { code: string }) => void }) => {
      options.success({ code: 'new-user-code' });
    },
  );
  wx.request.mockImplementation(
    (options: {
      method?: string;
      success: (result: {
        statusCode: number;
        data: unknown;
        header: object;
      }) => void;
      complete: () => void;
    }) => {
      options.success({
        statusCode: options.method === 'DELETE' ? 204 : 201,
        data:
          options.method === 'DELETE'
            ? undefined
            : {
                token: 'token-b',
                expires_at: '2030-01-01T00:00:00Z',
                user: { id: 'resident-b', enabled: true },
              },
        header: {},
      });
      options.complete();
      return { abort: vi.fn() };
    },
  );

  await session.login();
  expect(session.currentCredential()?.userId).toBe('resident-b');
  expect(storage.has(prefix + ':resident-house:resident-a')).toBe(false);
  expect(selection.getSelectedBindingId()).toBe('binding-b');

  await session.logout();
  expect(session.currentCredential()).toBeNull();
  expect(selection.getSelectedBindingId()).toBeNull();
  expect(storage.has(prefix + ':resident-house:resident-b')).toBe(false);
  expect(storage.get(otherScopeKey)).toBe('property-binding-b');
});
