import { App, ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import type { ReactNode } from 'react';

export function rootContainer(container: ReactNode) {
  return (
    <ConfigProvider locale={zhCN}>
      <App>{container}</App>
    </ConfigProvider>
  );
}
