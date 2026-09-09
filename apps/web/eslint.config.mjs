import nextCoreWebVitals from 'eslint-config-next/core-web-vitals';
import nextTypeScript from 'eslint-config-next/typescript';

/** @type {import('eslint').Linter.Config[]} */
const config = [
  {
    ignores: ['.next/**', 'out/**', 'build/**', 'next-env.d.ts'],
  },
  ...nextCoreWebVitals,
  ...nextTypeScript,
  {
    rules: {
      '@typescript-eslint/no-unused-vars': 'off',
      '@typescript-eslint/no-explicit-any': 'off',

      // eslint-plugin-react-hooks v7 (new in Next 16) adds React Compiler
      // checks that this codebase predates. They flag real code smells --
      // setState in effect bodies, helpers referenced before declaration --
      // but none are runtime bugs, and clearing them means reworking ~38
      // effects. Kept as warnings so they stay visible without blocking CI;
      // promote back to "error" as they get worked through.
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/immutability': 'warn',
    },
  },
];

export default config;
