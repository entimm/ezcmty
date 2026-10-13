import eslint from '@eslint/js';
import tseslint from 'typescript-eslint';
import globals from 'globals';

export default tseslint.config(
  { ignores: ['dist'] },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.ts'],
    languageOptions: { globals: { App: 'readonly', Page: 'readonly' } },
  },
  { files: ['**/*.mjs'], languageOptions: { globals: globals.node } },
);
