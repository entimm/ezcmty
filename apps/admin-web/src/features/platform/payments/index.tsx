import { useMemo } from 'react';
import { useAdmin } from '../../../shared/context';
import { PaymentsPage } from '../../../shared/payments/PaymentsPage';
import { platformPaymentReads, platformPaymentWrites } from './api';
import type { Choice, FlowPageProps } from '../../../shared/imports/runtime';
import type { Page } from '../../../shared/payments/types';
import { allOptions } from '../../../shared/imports/options';
export function PlatformPaymentsPage(props: FlowPageProps) {
  const admin = useAdmin();
  const api = useMemo(
    () => platformPaymentReads(admin.request),
    [admin.request],
  );
  const writes = useMemo(
    () => platformPaymentWrites(admin.request),
    [admin.request],
  );
  return (
    <PaymentsPage
      {...props}
      runtime={{
        scope: 'platform',
        api,
        writes,
        communityId: '',
        can: (permission) => admin.can(`platform.${permission}`),
        setDirty: admin.setDirty,
        companies: () =>
          allOptions((page) =>
            admin.request<Page<Choice>>(
              `/v1/property-company-options?page=${page}&page_size=100`,
            ),
          ),
      }}
    />
  );
}
