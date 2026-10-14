import eslint from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import { fileURLToPath, URL } from 'node:url';
import { createAdminBoundaryRule } from './config/lint/module-boundaries.mjs';

export default tseslint.config(
  { ignores: ['dist', 'coverage', 'src/.umi*/**'] },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.cjs'],
    languageOptions: { globals: globals.node },
  },
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.node },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': 'warn',
    },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    plugins: {
      'admin-boundaries': {
        rules: {
          imports: createAdminBoundaryRule(
            fileURLToPath(new URL('./src', import.meta.url)),
          ),
        },
      },
    },
    rules: { 'admin-boundaries/imports': 'error' },
  },
);
