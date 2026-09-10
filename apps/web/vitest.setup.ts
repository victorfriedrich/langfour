import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';

// Vitest runs with `globals: false`, so React Testing Library cannot install its
// own auto-cleanup (it looks for a global `afterEach`). Unmount between tests
// ourselves, or every render leaks into the next test's document.
afterEach(() => {
  cleanup();
});

// src/lib/supabaseclient.ts calls createClient() at module scope, so ANY module
// that transitively imports it throws "supabaseUrl is required" on import when
// these are unset. Fake values, never real credentials — no test should reach
// the network. Stub the client itself in tests that exercise queries.
process.env.NEXT_PUBLIC_SUPABASE_URL ||= 'http://localhost:54321';
process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||= 'test-anon-key-not-a-real-credential';

// Components using the app router throw outside a real Next render, and
// next/navigation is imported across a dozen-plus files. Override per-test with
// vi.mock('next/navigation') where a test needs specific route state.
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
  redirect: vi.fn(),
  notFound: vi.fn(),
}));
