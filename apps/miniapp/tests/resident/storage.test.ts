import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { device } from '../core/harness';
const current = 'https://new.example.invalid/api/client';
const legacy = 'https://old.example.invalid/api/resident';
let owner: string | null = 'resident-a';
let verified = true;
const key = (base: string, user = 'resident-a', kind = 'resident-payment') =>
  'ezcmty:' + base + ':' + kind + ':' + user + ':bill:bill-a';
const original = {
  key: 'mini_original_key',
  data: { items: [{ bill_id: 'bill-a', expected_row_version: 3 }] },
};
beforeEach(() => {
  vi.resetModules();
  owner = 'resident-a';
  verified = true;
  vi.doMock('../../src/config', () => ({
    API_BASE_URL: current,
    API_STORAGE_MIGRATIONS: [{ from: legacy, to: current }],
  }));
  vi.doMock('../../src/core/session', () => ({
    authenticatedUserId: () => (verified ? owner : null),
  }));
});
afterEach(() => {
  vi.doUnmock('../../src/config');
  vi.doUnmock('../../src/core/session');
  vi.unstubAllGlobals();
});
const normalize = (value: unknown) =>
  value && typeof value === 'object' && 'key' in value
    ? (value as typeof original)
    : undefined;
it('migrates only an explicitly mapped same-environment and authenticated-owner record', async () => {
  const { storage } = device();
  storage.set(key(legacy), original);
  storage.set(key(legacy, 'resident-b'), original);
  storage.set(key('https://unmapped.example.invalid/api/resident'), original);
  const helper = await import('../../src/packages/resident/storage');
  expect(
    helper.readStored('resident-payment', ':bill:bill-a', normalize),
  ).toEqual(original);
  expect(storage.get(key(current))).toEqual(original);
  expect(storage.has(key(legacy))).toBe(false);
  expect(storage.has(key(legacy, 'resident-b'))).toBe(true);
  expect(
    storage.has(key('https://unmapped.example.invalid/api/resident')),
  ).toBe(true);
});
it('will not read an old record before fresh client authentication confirms the owner', async () => {
  const { storage } = device();
  storage.set(key(legacy), original);
  verified = false;
  const helper = await import('../../src/packages/resident/storage');
  expect(() =>
    helper.readStored('resident-payment', ':bill:bill-a', normalize),
  ).toThrow();
  expect(storage.get(key(legacy))).toEqual(original);
  expect(storage.has(key(current))).toBe(false);
});
it.each(['write', 'readback'])(
  'retains the old recovery if migration %s cannot be verified',
  async (failure) => {
    const { wx, storage } = device();
    storage.set(key(legacy), original);
    if (failure === 'write')
      wx.setStorageSync.mockImplementation(() => {
        throw new Error('full');
      });
    else wx.setStorageSync.mockImplementation(() => {});
    const helper = await import('../../src/packages/resident/storage');
    expect(() =>
      helper.readStored('resident-payment', ':bill:bill-a', normalize),
    ).toThrow();
    expect(storage.get(key(legacy))).toEqual(original);
  },
);
it('does not infer a migration from similar or same-origin URLs', async () => {
  vi.doMock('../../src/config', () => ({
    API_BASE_URL: current,
    API_STORAGE_MIGRATIONS: [],
  }));
  const { storage } = device();
  storage.set(key(legacy), original);
  storage.set(key('https://new.example.invalid/api/resident'), original);
  const helper = await import('../../src/packages/resident/storage');
  expect(
    helper.readStored('resident-payment', ':bill:bill-a', normalize),
  ).toBeNull();
  expect(storage.has(key(current))).toBe(false);
});
it('preserves all stored recovery records across accounts while refusing another owner lookup', async () => {
  const { storage } = device();
  storage.set(key(current), original);
  owner = 'resident-b';
  const helper = await import('../../src/packages/resident/storage');
  expect(
    helper.readStored('resident-payment', ':bill:bill-a', normalize),
  ).toBeNull();
  expect(storage.get(key(current))).toEqual(original);
});
it('does not replace an existing different original payment during migration', async () => {
  const { storage } = device();
  storage.set(key(current), original);
  const other = { ...original, key: 'mini_other_key' };
  storage.set(key(legacy), other);
  const helper = await import('../../src/packages/resident/storage');
  expect(() =>
    helper.readStored('resident-payment', ':bill:bill-a', normalize),
  ).toThrow();
  expect(storage.get(key(current))).toEqual(original);
  expect(storage.get(key(legacy))).toEqual(other);
});
