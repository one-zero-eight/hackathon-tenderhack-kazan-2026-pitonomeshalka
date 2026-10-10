// `--relative` (passed by the pre-commit hook) hands these tasks file paths
// relative to this package, which is what ESLint and Prettier expect.
export default {
  '*.{js,mjs,cjs,ts,mts,tsx,vue}': 'eslint --fix',
  '*.{js,mjs,cjs,ts,mts,tsx,vue,json,jsonc,css,scss,md,yml,yaml}': 'prettier --write',
}
