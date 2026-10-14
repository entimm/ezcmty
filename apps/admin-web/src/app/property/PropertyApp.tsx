import { AdminScopeProvider } from '../../auth/AdminScopeProvider';
import { AdminRouter } from '../../auth/AdminRouter';

export default function PropertyApp() {
  return (
    <AdminScopeProvider scope="property_admin" authenticationEnabled>
      <AdminRouter />
    </AdminScopeProvider>
  );
}
