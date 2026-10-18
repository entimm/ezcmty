import { expect, it, vi } from 'vitest';
const request = vi.hoisted(() => vi.fn());
vi.mock('../../../src/auth/resident', () => ({ residentRequest: request }));
import {
  bill,
  bills,
  entries,
} from '../../../src/packages/resident/billing/api';
it('uses the current binding contract for house billing and separate read-only history', async () => {
  await bills('binding-id', 2, 'all');
  await bill('bill-id');
  await entries('bill-id', 3);
  expect(request.mock.calls.map(([path]) => path)).toEqual([
    '/miniapp-users/me/house-bindings/binding-id/bills?page=2&scope=all',
    '/miniapp-users/me/bills/bill-id',
    '/miniapp-users/me/bills/bill-id/settlement-entries?page=3',
  ]);
  expect(request.mock.calls.every((call) => call.length === 1)).toBe(true);
});
