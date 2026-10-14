import { App, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import type { ReactNode } from 'react';

import {
  patchAdminClientRoutes,
  type ScopedClientRoute,
} from './app/admin-routes';

export function patchClientRoutes({ routes }: { routes: ScopedClientRoute[] }) {
  patchAdminClientRoutes(routes);
}

export function rootContainer(container: ReactNode) {
  return (
    <ConfigProvider locale={zhCN}>
      <App>{container}</App>
    </ConfigProvider>
  );
}
