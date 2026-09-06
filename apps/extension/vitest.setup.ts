import { beforeEach, vi } from 'vitest';
import '@testing-library/jest-dom/vitest';

// src/supabaseclient.ts calls createClient() at module scope, so any module
// reaching it (backgroundScript, api-service, ...) throws on import when these
// are unset. Parcel substitutes them at build time; nothing substitutes them
// here. Fake values -- never real credentials, and no test should hit the
// network. Stub the client itself in tests that exercise queries.
process.env.REACT_APP_SUPABASE_URL ||= 'http://localhost:54321';
process.env.REACT_APP_SUPABASE_ANON_KEY ||= 'test-anon-key-not-a-real-credential';

/**
 * Minimal `chrome` stub. Importing almost any module under src/ touches
 * chrome.storage / chrome.runtime at load time, which is a ReferenceError in
 * happy-dom, so a fresh stub is installed before every test.
 *
 * The codebase calls storage BOTH ways -- `await storage.local.get([keys])` and
 * `storage.local.get(key, cb)` -- so every storage method here accepts an
 * optional trailing callback and otherwise returns a promise.
 */
type AnyFn = (...args: any[]) => any;

// Derived from the public key in manifest.json, so extension-page code follows
// the same runtime branch in tests as it does in Chrome.
const TEST_EXTENSION_ID = 'kjelgcbodejjpnidjflelanlbhbpkagb';

function dual(impl: AnyFn) {
  return vi.fn((...args: any[]) => {
    const callback = typeof args[args.length - 1] === 'function' ? (args.pop() as AnyFn) : undefined;
    const result = impl(...args);
    if (callback) {
      callback(result);
      return undefined;
    }
    return Promise.resolve(result);
  });
}

function makeStorageArea() {
  const store = new Map<string, unknown>();
  return {
    // Exposed so tests can seed or inspect state directly:
    //   (chrome.storage.local as any).__store.set('knownWords_de', ['der'])
    __store: store,
    get: dual((keys?: string | string[] | Record<string, unknown> | null) => {
      if (keys === undefined || keys === null) return Object.fromEntries(store);
      if (typeof keys === 'string') return store.has(keys) ? { [keys]: store.get(keys) } : {};
      if (Array.isArray(keys)) {
        const out: Record<string, unknown> = {};
        for (const k of keys) if (store.has(k)) out[k] = store.get(k);
        return out;
      }
      // Object form supplies defaults for missing keys.
      const out: Record<string, unknown> = {};
      for (const [k, fallback] of Object.entries(keys)) out[k] = store.has(k) ? store.get(k) : fallback;
      return out;
    }),
    set: dual((items: Record<string, unknown>) => {
      for (const [k, v] of Object.entries(items)) store.set(k, v);
    }),
    remove: dual((keys: string | string[]) => {
      for (const k of Array.isArray(keys) ? keys : [keys]) store.delete(k);
    }),
    clear: dual(() => {
      store.clear();
    }),
  };
}

export function createChromeStub() {
  return {
    storage: {
      local: makeStorageArea(),
      sync: makeStorageArea(),
      onChanged: { addListener: vi.fn(), removeListener: vi.fn() },
    },
    runtime: {
      id: TEST_EXTENSION_ID,
      // Code checks `if (chrome.runtime.lastError)` in dozens of places;
      // undefined is the success path. Set it in a test to hit the error branches.
      lastError: undefined as chrome.runtime.LastError | undefined,
      getURL: vi.fn((path: string) => `chrome-extension://${TEST_EXTENSION_ID}/${path}`),
      getManifest: vi.fn(() => ({ version: '1.1.1', manifest_version: 3 })),
      sendMessage: dual(() => undefined),
      onMessage: { addListener: vi.fn(), removeListener: vi.fn() },
    },
    tabs: {
      create: dual((props: Record<string, unknown>) => ({ id: 1, ...props })),
      get: dual((id: number) => ({ id, url: 'https://example.com' })),
      query: dual(() => [{ id: 1, active: true, url: 'https://example.com' }]),
      sendMessage: dual(() => undefined),
    },
    scripting: { executeScript: dual(() => [{ result: undefined }]) },
    commands: { onCommand: { addListener: vi.fn(), removeListener: vi.fn() } },
  };
}

// Installed at module scope as well as per-test: a test file's static imports
// are evaluated before beforeEach runs, and modules under src/ touch chrome as
// they load. beforeEach then hands each test a clean store.
//
// Consequence worth knowing: a statically imported module registers its
// listeners on the module-scope stub, so they are NOT in the per-test stub's
// call history. To assert import-time side effects (e.g. grabbing the
// onMessage handler to drive backgroundScript's routing), re-import per test:
//
//   beforeEach(async () => {
//     vi.resetModules();
//     await import('../backgroundScript');
//   });
//   const [handler] = vi.mocked(chrome.runtime.onMessage.addListener).mock.calls[0];
vi.stubGlobal('chrome', createChromeStub());

beforeEach(() => {
  vi.stubGlobal('chrome', createChromeStub());
});
