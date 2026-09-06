import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    name: 'extension',
    environment: 'happy-dom',
    setupFiles: ['./vitest.setup.ts'],
    // TEMPORARY -- remove when the first tests land.
    // Only here because no tests exist yet: without it, `npm test` (and any CI
    // step running it) exits 1 on "no test files found". It is not a setting to
    // keep: once tests exist it silently turns a broken `include` glob into a
    // green run that tested nothing, instead of a failure.
    passWithNoTests: true,
    include: ['src/**/*.{test,spec}.ts'],
  },
});
