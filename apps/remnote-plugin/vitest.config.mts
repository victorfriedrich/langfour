import { defineConfig } from 'vitest/config';

// A project of the root runner (vitest.config.mts), so `npm test` at the repo
// root runs these too; `npm test` here still works on its own.
export default defineConfig({
  test: {
    name: 'remnote-plugin',
    include: ['src/**/*.test.ts'],
  },
});
