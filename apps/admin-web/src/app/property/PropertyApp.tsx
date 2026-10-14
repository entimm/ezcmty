import { AdminAppProvider } from '../AdminAppProvider';
import { AdminRouter } from '../AdminRouter';
import { propertyApp } from './config';

export default function PropertyApp() {
  return (
    <AdminAppProvider app={propertyApp}>
      <AdminRouter />
    </AdminAppProvider>
  );
}
