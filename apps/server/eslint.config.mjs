import js from '@eslint/js';
import eslintConfigPrettier from 'eslint-config-prettier';
import onlyWarn from 'eslint-plugin-only-warn';
import tseslint from 'typescript-eslint';

// Inlined from the former @quant/eslint-config/base so this package installs
// without the workspace (D-09). eslint-plugin-turbo from that shared config is
// dropped deliberately: turbo does not manage this package while it is de-listed.

/** @type {import("eslint").Linter.Config[]} */
export default [
  js.configs.recommended,
  eslintConfigPrettier,
  ...tseslint.configs.recommended,
  { plugins: { onlyWarn } },
  { ignores: ['dist/**'] },
];
