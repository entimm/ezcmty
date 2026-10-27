import { expectTypeOf, it } from 'vitest';
import type {
  BillFilters,
  OrderFilters,
} from '../../src/packages/resident/api';
import type {
  ClaimInput,
  PaymentInput,
  ResidentBill,
} from '../../src/packages/resident/types';

it('uses the resident contract optional remark, nullable balance state, and one-bill payment input', () => {
  expectTypeOf<ClaimInput['applicant_remark']>().toEqualTypeOf<
    string | null | undefined
  >();
  expectTypeOf<ResidentBill['settlement_status']>().toEqualTypeOf<
    'unpaid' | 'partially_settled' | 'settled' | null
  >();
  expectTypeOf<PaymentInput['items']>().toEqualTypeOf<
    [{ bill_id: string; expected_row_version: number }]
  >();
});

it('keeps the public filter contracts separate from positional page and status arguments', () => {
  expectTypeOf<BillFilters['sort']>().toEqualTypeOf<
    '-billing_month,-id' | 'billing_month,id' | undefined
  >();
  expectTypeOf<OrderFilters['confirmation_status']>().toEqualTypeOf<
    'unconfirmed' | 'awaiting_posting' | 'posted' | undefined
  >();
  expectTypeOf<'page'>().not.toExtend<keyof BillFilters>();
  expectTypeOf<'scope'>().not.toExtend<keyof BillFilters>();
  expectTypeOf<'status'>().not.toExtend<keyof OrderFilters>();
});
