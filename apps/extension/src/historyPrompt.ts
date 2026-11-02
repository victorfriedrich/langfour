// The history consent as a small card in the bottom-right corner of
// youtube.com (watchHistory.ts has the read itself). Shown to a signed-in
// learner until they answer, and again when another Google account is
// signed in. Allow reads the history page straight away; Not now keeps it
// off until they turn it on from the extension menu.
//
// Its own module in the content script's isolated world, in a closed shadow
// root: the page can't reach its buttons and YouTube's styles can't reach
// in. Hidden in fullscreen.

import { getPrefs } from './preferencePopup/prefs';
import { getLanguageInfo } from './languages';
import { sendToBackground } from './messages';
import { consentText, historyState, HISTORY_CONSENT_KEY, HISTORY_DECLINED_ACCOUNTS_KEY, HISTORY_DECLINED_KEY, HISTORY_NEW_ACCOUNT_KEY } from './watchHistory';

const DONE_MS = 4000;

const CSS = `
:host { all: initial; }
.card {
  position: fixed; right: 24px; bottom: 24px; z-index: 2147483000; width: 340px; box-sizing: border-box;
  padding: 16px 18px; border: 1px solid #e5e7eb; border-radius: 12px; background: #fff; color: #111827;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
.title { margin: 0; font-size: 15px; font-weight: 600; }
.text { margin: 6px 0 0; color: #4b5563; }
.actions { margin-top: 14px; display: flex; align-items: center; gap: 8px; }
button {
  height: 34px; padding: 0 14px; border-radius: 8px; font: inherit; font-weight: 500; cursor: pointer;
  border: 1px solid #e5e7eb; background: #fff; color: #374151;
}
button.primary { border-color: #4f46e5; background: #4f46e5; color: #fff; }
button:disabled { opacity: 0.5; cursor: default; }
.error { margin: 8px 0 0; color: #b91c1c; font-size: 13px; }
:host-context(html[dark]) .card { background: #212121; border-color: #3f3f3f; color: #f1f1f1; }
:host-context(html[dark]) .text { color: #c4c4c4; }
:host-context(html[dark]) button:not(.primary) { background: #212121; border-color: #3f3f3f; color: #f1f1f1; }
`;

function ask<T>(message: Parameters<typeof sendToBackground>[0]): Promise<T | undefined> {
  return new Promise((resolve) => {
    try {
      sendToBackground<T>(message, (r) => resolve(chrome.runtime.lastError ? undefined : r));
    } catch {
      resolve(undefined); // the extension was reloaded under this page
    }
  });
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className: string, text = ''): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}

async function shouldAsk(): Promise<boolean> {
  const stored = await chrome.storage.local.get(['supabaseSession', HISTORY_CONSENT_KEY, HISTORY_DECLINED_KEY, HISTORY_NEW_ACCOUNT_KEY]);
  return !!stored.supabaseSession && historyState(stored) === 'ask';
}

function languageName(): Promise<string> {
  return new Promise((resolve) => getPrefs((prefs) => resolve(getLanguageInfo(prefs.preferredLanguage)?.name ?? 'learning-language')));
}

export function promptForHistory(): void {
  let host: HTMLElement | null = null;
  let allowing = false; // this card's Allow is running or showing "Done"

  const close = () => {
    host?.remove();
    host = null;
    allowing = false;
  };

  const show = async () => {
    if (host || !(await shouldAsk())) return;
    const language = await languageName();
    if (host) return;
    host = document.createElement('langfour-history');
    const root = host.attachShadow({ mode: 'closed' });
    const style = document.createElement('style');
    style.textContent = CSS;
    const card = el('div', 'card');
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-label', 'Use your YouTube history?');
    const allow = el('button', 'primary', 'Allow');
    const later = el('button', '', 'Not now');
    const error = el('p', 'error');
    error.hidden = true;
    const actions = el('div', 'actions');
    actions.append(allow, later);
    card.append(
      el('p', 'title', 'Use your YouTube history?'),
      el('p', 'text', consentText(language)),
      actions,
      error,
    );
    root.append(style, card);
    document.documentElement.append(host);

    // Only the user's own clicks count, never one the page fakes.
    allow.addEventListener('click', async (event) => {
      if (!event.isTrusted) return;
      allow.disabled = later.disabled = true;
      allowing = true;
      error.hidden = true;
      const result = await ask<{ kept?: number; error?: string }>({ type: 'HISTORY_ALLOW' });
      if (!result || result.error) {
        allow.disabled = later.disabled = false;
        allowing = false;
        error.textContent = result?.error === 'Not signed in to YouTube'
          ? 'Sign in to YouTube first.'
          : 'Could not read your history. Try again later.';
        error.hidden = false;
        return;
      }
      actions.replaceChildren(el('span', 'text', 'Done. You can turn it off in the Langfour menu.'));
      setTimeout(close, DONE_MS);
    });
    later.addEventListener('click', async (event) => {
      if (!event.isTrusted) return;
      close();
      // For another account, "not now" is remembered for that account, or
      // the next read would ask again.
      const stored = await chrome.storage.local.get([HISTORY_NEW_ACCOUNT_KEY, HISTORY_DECLINED_ACCOUNTS_KEY]);
      const declined: unknown[] = Array.isArray(stored[HISTORY_DECLINED_ACCOUNTS_KEY]) ? stored[HISTORY_DECLINED_ACCOUNTS_KEY] : [];
      await chrome.storage.local.set({
        [HISTORY_DECLINED_KEY]: true,
        [HISTORY_NEW_ACCOUNT_KEY]: false,
        [HISTORY_DECLINED_ACCOUNTS_KEY]: stored[HISTORY_NEW_ACCOUNT_KEY] ? [...declined, stored[HISTORY_NEW_ACCOUNT_KEY]] : declined,
      });
    });
  };

  void show();
  // Asked again from the menu, or another account noticed by the background.
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local') return;
    if (changes[HISTORY_DECLINED_KEY] || changes[HISTORY_NEW_ACCOUNT_KEY] || changes[HISTORY_CONSENT_KEY] || changes.supabaseSession) {
      // Answered in another tab: this one's card goes too.
      void shouldAsk().then((asking) => (asking ? show() : allowing ? undefined : close()));
    }
  });
  document.addEventListener('fullscreenchange', () => {
    if (host) host.style.display = document.fullscreenElement ? 'none' : '';
  });
}
