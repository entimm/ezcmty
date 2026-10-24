import { defineConfig } from '@umijs/max';
const platform = process.env.UMI_APP_PLATFORM_API_BASE || '/api/platform';
const property = process.env.UMI_APP_PROPERTY_API_BASE || '/api/property';
export default defineConfig({
  npmClient: 'pnpm',
  title: process.env.UMI_APP_NAME || '邻里云 · 社区物业平台',
  routes: [{ path: '/*', component: '@/app/App' }],
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
  proxy: Object.fromEntries(
    [
      [platform, 8001],
      [property, 8002],
    ].map(([prefix, port]) => [
      prefix,
      {
        target: `http://127.0.0.1:${port}`,
        changeOrigin: false,
        pathRewrite: (path: string) => path.slice(String(prefix).length) || '/',
      },
    ]),
  ),
});
