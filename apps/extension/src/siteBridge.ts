// Runs only on the Langfour web app. Lets the site detect the extension and
// its sign-in state without knowing the extension ID: the page pings via
// window.postMessage and this script answers. Only the account email and
// version are shared, never tokens.

const PAGE_SOURCE = 'langfour-web';
const EXTENSION_SOURCE = 'langfour-extension';

type Status = { installed: true; version: string; signedIn: boolean; email: string | null };

async function readStatus(): Promise<Status> {
  const { supabaseSession } = await chrome.storage.local.get('supabaseSession');
  const email: string | null = supabaseSession?.user?.email ?? null;
  return {
    installed: true,
    version: chrome.runtime.getManifest().version,
    signedIn: Boolean(supabaseSession?.access_token),
    email,
  };
}

async function announce(): Promise<void> {
  // Message only: writing to the DOM (e.g. a data attribute on <html>) before
  // React hydrates makes Next.js report a hydration mismatch.
  const status = await readStatus();
  window.postMessage({ source: EXTENSION_SOURCE, type: 'STATUS', status }, window.location.origin);
}

window.addEventListener('message', (event) => {
  if (event.source !== window || event.data?.source !== PAGE_SOURCE || event.data?.type !== 'PING') return;
  void announce();
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.supabaseSession) void announce();
});

void announce();
