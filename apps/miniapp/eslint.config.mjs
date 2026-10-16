import eslint from '@eslint/js';
import tseslint from 'typescript-eslint';
import globals from 'globals';

export default tseslint.config(
  { ignores: ['dist', '.tmp'] },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.ts', 'tests/**/*.ts'],
    languageOptions: {
      globals: {
        App: 'readonly',
        Page: 'readonly',
        wx: 'readonly',
        Component: 'readonly',
      },
    },
  },
  { files: ['**/*.mjs'], languageOptions: { globals: globals.node } },
);
