import { describe, expect, it, vi } from 'vitest';
import { createPropertyApi } from '../../../src/features/property/api';
import type {
  BillAction,
  BillSubmission,
} from '../../../src/shared/property-business/types';
import type { AdminRequest } from '../../../src/shared/request';

const target = {
  companyId: 'company-1',
  communityId: 'community-1',
  billId: 'bill-1',
  entryId: 'entry-1',
};

describe('物业账务动作适配', () => {
  it.each<[BillAction, string, string]>([
    ['create', '/v1/communities/community-1/bills', 'POST'],
    ['edit', '/v1/communities/community-1/bills/bill-1', 'PATCH'],
    [
      'receipt',
      '/v1/communities/community-1/bills/bill-1/offline-receipts',
      'POST',
    ],
    [
      'correct',
      '/v1/communities/community-1/bills/bill-1/offline-receipts/entry-1/corrections',
      'POST',
    ],
    [
      'reverse',
      '/v1/communities/community-1/bills/bill-1/offline-receipts/entry-1/reversals',
      'POST',
    ],
    ['void', '/v1/communities/community-1/bills/bill-1/voids', 'POST'],
  ])('%s 保留原接口、输入与幂等键', async (action, path, method) => {
    const request = vi.fn().mockResolvedValue({}) as unknown as AdminRequest;
    const body = {
      expected_row_version: 7,
      reason: '已核实',
      amount_cents: 10000,
    };
    const submission: BillSubmission = {
      ...target,
      action,
      body,
      billId: action === 'create' ? undefined : target.billId,
    };
    await createPropertyApi(request).submitBill(submission, 'original-key');
    expect(request).toHaveBeenCalledExactlyOnceWith(path, {
      method,
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': 'original-key',
      },
      body: JSON.stringify(body),
    });
  });

  it.each(['companyId', 'communityId', 'billId', 'entryId'] as const)(
    '恢复目标缺少 %s 时拒绝发送',
    (field) => {
      const request = vi.fn() as unknown as AdminRequest;
      const submission = {
        ...target,
        action: 'correct' as const,
        body: {},
        [field]: '',
      };
      expect(() =>
        createPropertyApi(request).submitBill(submission, 'original-key'),
      ).toThrow('原账务操作范围或资源不完整');
      expect(request).not.toHaveBeenCalled();
    },
  );
});
