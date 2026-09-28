import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      // Initial data fetches set loading state before the request resolves.
      'react-hooks/set-state-in-effect': 'off',
    },
  },
  {
    files: ['src/PlayerProfile.jsx', 'src/auth.jsx'],
    rules: {
      // These modules intentionally export shared UI helpers alongside components.
      'react-refresh/only-export-components': 'off',
    },
  },
])
