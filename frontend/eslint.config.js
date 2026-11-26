// @ts-check
import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist/**', 'coverage/**', 'node_modules/**'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    plugins: { 'react-hooks': reactHooks },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // `any` is used widely at API and test-fixture boundaries; `tsc` (strict)
      // remains the type gate. Narrow these gradually rather than by mass edit.
      '@typescript-eslint/no-explicit-any': 'off',
      // A leading underscore marks an intentionally unused name.
      '@typescript-eslint/no-unused-vars': ['error', {
        argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_',
      }],
      // Allow `let` when a closure reads the binding before its single assignment.
      'prefer-const': ['error', { ignoreReadBeforeAssign: true }],
    },
  },
);
