import { AdminScopeProvider } from '../../auth/AdminScopeProvider';
import { AdminRouter } from '../../auth/AdminRouter';

export default function PlatformApp() {
  return (
    <AdminScopeProvider scope="platform_admin" authenticationEnabled>
      <AdminRouter />
    </AdminScopeProvider>
  );
}
