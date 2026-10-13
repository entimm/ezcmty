import { AdminScopeProvider } from '../../auth/AdminScopeProvider';
import { AdminLayout } from '../AdminLayout';

export default function PlatformApp() {
  return (
    <AdminScopeProvider scope="platform_admin">
      <AdminLayout scope="platform_admin" />
    </AdminScopeProvider>
  );
}
