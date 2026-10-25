import { useMemo } from 'react';
import { useAdmin } from '../../../shared/context';
import { PaymentsPage } from '../../../shared/payments/PaymentsPage';
import { propertyPaymentReads } from './api';
import type { FlowPageProps } from '../../../shared/imports/runtime';
export function PropertyPaymentsPage(props: FlowPageProps) {
  const admin = useAdmin();
  const api = useMemo(
    () => propertyPaymentReads(admin.request),
    [admin.request],
  );
  return (
    <PaymentsPage
      {...props}
      runtime={{
        scope: 'property',
        api,
        communityId: admin.communityId,
        community: admin.community,
        can: (permission) =>
          [
            'payment.read',
            'payment_reconciliation.read',
            'payment_config.read',
          ].includes(permission) && admin.can('property.payment.read'),
        setDirty: admin.setDirty,
      }}
    />
  );
}
