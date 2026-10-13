import { AdminScopeProvider } from '../../auth/AdminScopeProvider';
import { AdminLayout } from '../AdminLayout';

export default function PropertyApp() {
  return (
    <AdminScopeProvider scope="property_admin">
      <AdminLayout scope="property_admin" />
    </AdminScopeProvider>
  );
}
