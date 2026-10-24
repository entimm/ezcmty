import { useAdmin } from '../../shared/context';
import { NoAccess, NotFound } from '../../shared/ui';
import { HousingPage } from './Housing';
import { BillingPage } from './Billing';
import { ClaimsPage, BindingsPage } from './Residents';
import { CommunitiesPage, CompanyPage } from './Communities';

export function PropertyPages({
  page,
}: {
  page: string;
  params?: Record<string, string>;
  go?: (page: string, params?: Record<string, string | undefined>) => void;
}) {
  const { scope, can, go } = useAdmin();
  if (scope !== 'property') return <NoAccess />;
  const readPermission = page.startsWith('house')
    ? 'property.house.read'
    : page.startsWith('bill')
      ? 'property.bill.read'
      : page.startsWith('claim')
        ? 'property.house_claim.read'
        : page.startsWith('binding')
          ? 'property.resident_house_binding.read'
          : page === 'communities'
            ? 'property.community.read'
            : page === 'company'
              ? 'property.company.read'
              : undefined;
  if (readPermission && !can(readPermission))
    return <NoAccess back={() => go('home')} />;
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
