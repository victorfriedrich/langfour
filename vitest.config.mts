import { defineConfig } from 'vitest/config';

// Root runner: `npm test` executes every workspace project.
// Each project owns its config (apps/*/vitest.config.mts).
export default defineConfig({
  test: {
    // TEMPORARY -- remove when the first tests land, together with the matching
    // lines in apps/*/vitest.config.mts. The projects runner does its own
    // "no test files" check, so the per-project setting alone leaves this exit 1.
    passWithNoTests: true,
    projects: ['apps/web', 'apps/extension'],
  },
});
