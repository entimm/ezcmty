import { defineConfig } from '@umijs/max';

import routes from './routes';

const platformApiBase =
  process.env.UMI_APP_PLATFORM_API_BASE || '/api/platform';
const propertyApiBase =
  process.env.UMI_APP_PROPERTY_API_BASE || '/api/property';

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
  plugins: ['./config/plugins/dev-server.ts'],
  proxy: {
    [platformApiBase]: {
      target: 'http://127.0.0.1:8001',
      changeOrigin: true,
      pathRewrite: (path: string) => path.slice(platformApiBase.length) || '/',
    },
    [propertyApiBase]: {
      target: 'http://127.0.0.1:8002',
      changeOrigin: true,
      pathRewrite: (path: string) => path.slice(propertyApiBase.length) || '/',
    },
  },
});
