import { expect, it, vi } from 'vitest';
import { requestPayment } from '../../../src/shared/wechat/payment';
import { safeReturn } from '../../../src/shared/wechat/ui';
it.each([
  ['requestPayment:fail cancel', 'cancelled'],
  ['requestPayment:fail network', 'unknown'],
])('maps %s without deciding funds success', async (errMsg, expected) => {
  vi.stubGlobal('wx', {
    requestPayment: (options: WechatMiniprogram.RequestPaymentOption) =>
      options.fail?.({ errMsg }),
  });
  await expect(
    requestPayment({
      timeStamp: '1',
      nonceStr: 'nonce',
      package: 'prepay_id=x',
      signType: 'RSA',
      paySign: 'signature',
    }),
  ).resolves.toBe(expected);
});
it('allows payment routes with ordinary identifiers and rejects credential query strings', () => {
  const path =
    '/packages/resident/pages/payment-detail/index?id=12345678-1234-1234-1234-123456789abc';
  expect(safeReturn(encodeURIComponent(path))).toBe(path);
  expect(safeReturn(path + '&paySign=secret')).toBe(
    '/packages/resident/pages/home/index',
  );
});
