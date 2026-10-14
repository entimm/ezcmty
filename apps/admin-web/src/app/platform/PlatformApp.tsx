import { AdminAppProvider } from '../AdminAppProvider';
import { AdminRouter } from '../AdminRouter';
import { platformApp } from './config';

export default function PlatformApp() {
  return (
    <AdminAppProvider app={platformApp}>
      <AdminRouter />
    </AdminAppProvider>
  );
}
