import js from '@eslint/js'
import { vueTsConfigs, withVueTs } from '@vue/eslint-config-typescript'
import pluginPrettierRecommended from 'eslint-plugin-prettier/recommended'
import pluginVue from 'eslint-plugin-vue'
import { globalIgnores } from 'eslint/config'
import globals from 'globals'

export default withVueTs(
  {
    name: 'app/files-to-lint',
    files: ['**/*.{js,mjs,cjs,ts,mts,tsx,vue}'],
  },
  globalIgnores(['**/dist/**', '**/dist-ssr/**', '**/coverage/**', '**/node_modules/**']),
  js.configs.recommended,
  pluginVue.configs['flat/recommended'],
  vueTsConfigs.recommended,
  {
    name: 'app/language-options',
    languageOptions: {
      globals: {
        ...globals.browser,
      },
    },
  },
  // Reported formatting differences are lint errors, and rules that would
  // fight with Prettier are switched off.
  pluginPrettierRecommended,
  {
    // Limits mirror the reference setup in github.com/projacktor/finsec-train
    // (complexity 15, 300 lines per file) plus a hard line-length ceiling.
    // Declared after the Prettier preset on purpose: eslint-config-prettier
    // switches `max-len` off, and the ceiling is a project requirement.
    name: 'app/code-quality',
    files: ['**/*.{js,mjs,cjs,ts,mts,tsx,vue}'],
    rules: {
      complexity: ['error', { max: 15 }],
      'max-lines': ['error', { max: 300, skipBlankLines: true, skipComments: true }],
      'max-len': [
        'error',
        {
          code: 100,
          tabWidth: 2,
          ignoreComments: true,
          ignoreTrailingComments: true,
          ignoreUrls: true,
          ignoreStrings: true,
          ignoreTemplateLiterals: true,
          ignoreRegExpLiterals: true,
        },
      ],
      // Attribute order is owned by prettier-plugin-organize-attributes
      // (alphabetical, `attributeSort: ASC`), which contradicts this rule's
      // group order. Keep the deterministic Prettier sort.
      'vue/attributes-order': 'off',
    },
  },
)
