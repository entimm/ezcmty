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
        replacement: fileURLToPath(new URL('./tests/umi.ts', import.meta.url)),
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
    include: ['tests/**/*.{test,spec}.{js,jsx,mjs,cjs,ts,tsx,mts,cts}'],
    setupFiles: './tests/setup.ts',
    globals: true,
    server: { deps: { inline: ['@ant-design/pro-components', 'antd'] } },
    exclude: ['**/node_modules/**', '**/.umi*/**', '**/dist/**'],
  },
});
