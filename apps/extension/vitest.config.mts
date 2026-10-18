import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    name: 'extension',
    environment: 'happy-dom',
    setupFiles: ['./vitest.setup.ts'],
    include: ['src/**/*.{test,spec}.ts'],
  },
});
