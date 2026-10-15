import { defineConfig } from '@umijs/max';

import routes from './routes';
import { platformApp } from '../src/app/platform/config';
import { propertyApp } from '../src/app/property/config';

const platformApiBase = platformApp.apiBase;
const propertyApiBase = propertyApp.apiBase;

export default defineConfig({
  npmClient: 'pnpm',
  title: process.env.UMI_APP_NAME || '社区物业平台',
  routes,
  history: { type: 'browser' },
  hash: true,
  outputPath: 'dist',
  fastRefresh: true,
  esbuildMinifyIIFE: true,
  mfsu: false,
  antd: {},
  layout: false,
  plugins: [
    './config/plugins/dev-server.ts',
    './config/plugins/setup-types.ts',
  ],
  // Umi 会随 changeOrigin 改写 Origin，需保留浏览器来源供 CSRF 校验。
  proxy: {
    [platformApiBase]: {
      target: 'http://127.0.0.1:8001',
      changeOrigin: false,
      pathRewrite: (path: string) => path.slice(platformApiBase.length) || '/',
    },
    [propertyApiBase]: {
      target: 'http://127.0.0.1:8002',
      changeOrigin: false,
      pathRewrite: (path: string) => path.slice(propertyApiBase.length) || '/',
    },
  },
});
