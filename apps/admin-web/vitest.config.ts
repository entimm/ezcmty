import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  resolve: {
    alias: [
      {
        find: '@',
        replacement: fileURLToPath(new URL('./src', import.meta.url)),
      },
      {
        find: '@umijs/max',
        replacement: fileURLToPath(
          new URL('./src/test/umi.ts', import.meta.url),
        ),
      },
      {
        // Transform extensionless locale imports through Vite's ES loader.
        find: /^@ant-design\/pro-components$/,
        replacement: fileURLToPath(
          new URL(
            './node_modules/@ant-design/pro-components/es/index.js',
            import.meta.url,
          ),
        ),
      },
    ],
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    globals: true,
    server: { deps: { inline: ['@ant-design/pro-components', 'antd'] } },
    exclude: ['**/node_modules/**', '**/.umi*/**', '**/dist/**'],
  },
});
