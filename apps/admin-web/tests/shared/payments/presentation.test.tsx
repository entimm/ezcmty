import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { FundsProgress } from '@/shared/payments/FundsProgress';
import { DiscrepancySummary } from '@/shared/payments/DiscrepancySummary';
import {
  estimateSharing,
  money,
  parsePercent,
} from '@/shared/payments/presentation';
import { difference } from '../../support/payments';
it.each([
  ['0', 0],
  ['0.01', 1],
  ['3.25', 325],
  ['100.00', 10000],
])('converts %s percent exactly to basis points', (value, expected) =>
  expect(parsePercent(value)).toBe(expected),
);
it.each(['-1', '1.001', '100.01', 'NaN'])(
  'rejects invalid percentage %s',
  (value) => expect(() => parsePercent(value)).toThrow(),
);
it('rounds half-up at a cent boundary using exact integer arithmetic', () => {
  expect(estimateSharing(50, 100)).toBe(1);
  expect(estimateSharing(49, 100)).toBe(0);
  expect(money(null)).toBe('待核对');
});
it('keeps unknown release amounts and resolved differences separate from funds success', () => {
  render(
    <>
      <FundsProgress
        sharing={[]}
        unfreezing={[
          {
            id: 'unfreeze',
            property_company_id: 'company',
            payment_order_id: 'payment',
            order_no: 'UNFREEZE1',
            channel_order_no: null,
            status: 'unknown',
            unfrozen_cents: null,
            channel_detail_no: null,
            failure_summary: null,
            finished_at: null,
            created_at: '',
            updated_at: '',
          },
        ]}
      />
      <DiscrepancySummary item={{ ...difference, status: 'resolved' }} />
    </>,
  );
  expect(screen.getAllByText('待核对').length).toBeGreaterThan(0);
  expect(screen.getByText('差异已解决')).toBeInTheDocument();
  expect(screen.queryByText('物业已到账')).not.toBeInTheDocument();
});
