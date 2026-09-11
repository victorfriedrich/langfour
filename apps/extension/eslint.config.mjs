import js from '@eslint/js';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: ['dist/**', '.parcel-cache/**', 'static/**', 'types/**'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.ts'],
    rules: {
      quotes: ['error', 'single'],
      'object-curly-spacing': ['error', 'always'],
    },
  },
);
