import { useAdmin } from '../../shared/context';
import { NoAccess, NotFound } from '../../shared/ui';
import { HousingPage } from './Housing';
import { BillingPage } from './Billing';
import { ClaimsPage, BindingsPage } from './Residents';
import { CommunitiesPage, CompanyPage } from './Communities';
import { SystemPages } from '../../shared/system/SystemPages';

export function PropertyPages({
  page,
}: {
  page: string;
  params?: Record<string, string>;
  go?: (page: string, params?: Record<string, string | undefined>) => void;
}) {
  const { scope, can, go, params: contextParams } = useAdmin();
  if (scope !== 'property') return <NoAccess />;
  const readPermission = page.startsWith('house')
    ? 'property.housing.read'
    : page.startsWith('bill')
      ? 'property.bill.read'
      : page.startsWith('claim')
        ? 'property.resident_access.read'
        : page.startsWith('binding')
          ? 'property.resident_access.read'
          : undefined;
  if (readPermission && !can(readPermission))
    return <NoAccess back={() => go('home')} />;
  if (['accounts', 'roles', 'audit'].includes(page))
    return <SystemPages page={page} params={contextParams} go={go} />;
  if (page === 'houses' || page === 'house-detail')
    return <HousingPage detail={page === 'house-detail'} />;
  if (page === 'bills' || page === 'bill-detail')
    return <BillingPage detail={page === 'bill-detail'} />;
  if (page === 'claims' || page === 'claim-detail')
    return <ClaimsPage detail={page === 'claim-detail'} />;
  if (page === 'bindings' || page === 'binding-detail')
    return <BindingsPage detail={page === 'binding-detail'} />;
  if (page === 'communities') return <CommunitiesPage />;
  if (page === 'company') return <CompanyPage />;
  return <NotFound back={() => go('home')} />;
}
