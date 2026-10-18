import { screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { renderRoutes } from '../../../app/platform-harness';
import { identity, mockPayments, paymentId } from '../../../support/payments';
import { createPropertyPaymentsApi } from '@/features/property/payments/api';
afterEach(() => vi.unstubAllGlobals());
it('keeps payment and reconciliation APIs read-only and strips foreign company filters', async () => {
  const paths: string[] = [];
  const api = createPropertyPaymentsApi(async <T,>(path: string) => {
    paths.push(path);
    return undefined as T;
  });
  await api.orders({ property_company_id: 'foreign', page: 1 });
  await api.runs({ property_company_id: 'foreign' });
  expect(paths.every((path) => !path.includes('foreign'))).toBe(true);
  for (const method of [
    'recover',
    'externalResolution',
    'createBinding',
    'createRule',
    'activate',
    'recheck',
    'recoverDifference',
  ])
    expect(api).not.toHaveProperty(method);
});
it('reads payment and posting without requesting funds without its independent permission', async () => {
  const fetcher = mockPayments(
    identity('property_admin', ['property.payment.read']),
  );
  renderRoutes(`/property/payments/${paymentId}`);
  expect(await screen.findByText('账单已入账')).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: /恢复/ }),
  ).not.toBeInTheDocument();
  expect(
    fetcher.mock.calls.some(([url]) =>
      /profit-sharing-orders|payment-unfreeze-orders/.test(String(url)),
    ),
  ).toBe(false);
});
it('shows only company reconciliation reads without external resolution or recovery controls', async () => {
  mockPayments(
    identity('property_admin', ['property.payment_reconciliation.read']),
  );
  renderRoutes(`/property/payment-reconciliation?difference=${paymentId}`);
  expect(await screen.findByText('本公司差异')).toBeInTheDocument();
  expect(await screen.findByText('判定来源')).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '记录外部处置' }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: '恢复原业务' }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText('平台资金记账')).not.toBeInTheDocument();
});
