// ESLint after the Vite template for React and TypeScript.
//
// The threshold is zero warnings and stays zero: `npm run lint` runs
// `eslint . --max-warnings 0`, the same in CI. Without a threshold ESLint
// returns exit code 0 on warnings and the step could never fail.
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['**/dist/**', '**/dev-dist/**', 'playwright-report/**', 'test-results/**', 'coverage/**'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
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
      // Files here export helpers next to components on purpose; HMR granularity is not worth the split.
      'react-refresh/only-export-components': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_', destructuredArrayIgnorePattern: '^_' }],
      // Syncing store state from a query result inside an effect is the
      // established pattern here; the compiler-family rules flag it.
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/exhaustive-deps': 'warn',
    },
  },
)
