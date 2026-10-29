import eslint from '@eslint/js';
import tseslint from 'typescript-eslint';
import hooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
export default tseslint.config(
  { ignores: ['node_modules/**', 'dist/**', 'coverage/**', 'src/.umi*/**'] },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    plugins: { 'react-hooks': hooks },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
    },
  },
  { files: ['**/*.cjs'], languageOptions: { globals: globals.node } },
  {
    files: ['src/features/platform/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        { patterns: ['**/features/property/**', '**/property/*'] },
      ],
    },
  },
  {
    files: ['src/features/property/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        { patterns: ['**/features/platform/**', '**/platform/*'] },
      ],
    },
  },
  {
    files: ['src/shared/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        { patterns: ['**/features/**', '**/app/**'] },
      ],
    },
  },
  {
    files: ['src/shared/property-business/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: ['**/features/**', '**/app/**', '**/context', '**/hooks'],
        },
      ],
      'no-restricted-syntax': [
        'error',
        {
          selector: 'Literal[value=/^property\\./]',
          message: '共享物业业务只判断业务动作，后台权限码由端内适配映射。',
        },
      ],
    },
  },
);
