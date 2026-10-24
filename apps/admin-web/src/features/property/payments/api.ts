import type { AdminRequest } from '../../../shared/request';
import { query } from '../../../shared/imports/api';
import { paymentReads } from '../../../shared/payments/api';
import type { PaymentReadApi } from '../../../shared/payments/runtime';
import type {
  MerchantBinding,
  Page,
  PaymentConfiguration,
  RuleVersion,
} from '../../../shared/payments/types';
export function propertyPaymentReads(request: AdminRequest): PaymentReadApi {
  return {
    ...paymentReads(request, (filters) =>
      Object.fromEntries(
        Object.entries(filters).filter(
          ([key]) => key !== 'property_company_id',
        ),
      ),
    ),
    configuration: () =>
      request<PaymentConfiguration>('/v1/payment-configuration'),
    bindings: (_, filters) =>
      request<Page<MerchantBinding>>(`/v1/merchant-bindings?${query(filters)}`),
    rules: (_, filters) =>
      request<Page<RuleVersion>>(
        `/v1/profit-sharing-rule-versions?${query(filters)}`,
      ),
  };
}
