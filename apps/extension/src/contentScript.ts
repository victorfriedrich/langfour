import { getPrefs } from './preferencePopup/prefs';
import { injectCss, injectJs, logPrefix } from './utils';
import { Language, toLanguage } from './languages';
import { Readability } from '@mozilla/readability';
import { getStoredWords } from './wordstorage';
import { ContentScriptMessage, sendToBackground } from './messages';
import { KnownWordsEvent } from './types';
import { isAllowedHost } from './siteApi';
import { getErrorMessage } from './errors';

export type Prefs = {
  preferredLanguage: Language;
};

let prefs: Prefs | null = null;

/**
 * Loads preferences, dispatches them to other parts of the extension,
 * and then checks/refreshes the known words cache.
 */
function sendCurrentPrefsToInjectedScripts(): void {
  getPrefs((newPrefs) => {
    document.dispatchEvent(new CustomEvent('prefs', { detail: newPrefs }));
    prefs = newPrefs;
    relayKnownWordsToPage(determineLanguage(newPrefs));
    // On every page (not just YouTube) check cache validity.
    checkCacheAndRefreshWords();
  });
}

/**
 * The language key used for known words. Preferences already hold the ISO
 * code the rest of the system uses, so this only normalises legacy values
 * (a long name written to chrome.storage.sync before the ISO cutover).
 *
 * Returns null rather than falling back to a language: the previous
 * `default: 'spanish'` silently served Spanish words to French learners,
 * because `'fr'` had no case.
 */
function determineLanguage(prefs: Prefs): Language | null {
  return toLanguage(prefs.preferredLanguage);
}

/**
 * The MAIN-world injected script (index.ts) has no chrome.storage/chrome.runtime
 * access, so it can't read the known-words cache itself. This relays it over
 * via a CustomEvent on `document`, which both worlds share, the same way
 * prefs are relayed above.
 */
function relayKnownWordsToPage(lang: Language | null): void {
  if (!lang) return;
  getStoredWords(lang).then((words) => {
    document.dispatchEvent(new CustomEvent<KnownWordsEvent>('known-words', {
      detail: { language: lang, words: Array.from(words) },
    }));
  });
}

// Keep the injected page script's copy live once the background finishes
// writing a fresh known-words cache.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local' || !prefs) return;
  const lang = determineLanguage(prefs);
  if (lang && changes[`knownWords_${lang}`]) {
    relayKnownWordsToPage(lang);
  }
});

// index.ts (MAIN world) dispatches these on `document` for analytics, but
// has no chrome.runtime access to send them itself. Relay them to the
// background, same as the known-words cache above.
document.addEventListener('view-popup', () => {
  sendToBackground({ type: 'view-popup' });
});
document.addEventListener('session', () => {
  sendToBackground({ type: 'session' });
});

// Reader extraction can inject this content script into any user-invoked
// active tab. Only install the subtitle UI on the sites it actually supports;
// unsupported pages need the EXTRACT_ARTICLE listener below and nothing else.
if (isAllowedHost(location.host)) {
  injectCss('src/index.css');
  injectJs('src/index.js').then(sendCurrentPrefsToInjectedScripts);
  if (location.host === 'www.youtube.com') {
    injectJs('src/youtubeBookmark.js');
  }
}

/**
 * Asks the background service worker to check the known-words cache against
 * Supabase and refresh it if stale. The background is the only context that
 * holds a Supabase client/session; this content script never touches
 * Supabase directly.
 */
function checkCacheAndRefreshWords(): void {
  if (!prefs) return;
  const lang = determineLanguage(prefs);
  if (!lang) {
    console.warn(logPrefix, 'Unrecognised preferred language; skipping known-words refresh:', prefs.preferredLanguage);
    return;
  }

  // main moved the Supabase call into the background service worker, which is
  // now the only context holding a session. The per-language timestamp fix
  // this branch made here moves with it, into backgroundScript's
  // refreshKnownWordsIfStale.
  sendToBackground<{ success: boolean; error?: string }>(
    { type: 'REFRESH_KNOWN_WORDS', language: lang },
    (response) => {
      if (chrome.runtime.lastError) {
        console.error(logPrefix, 'Error refreshing known words:', chrome.runtime.lastError);
        return;
      }
      if (!response?.success) {
        // Not signed in is an expected, routine state (fires on every page
        // load while logged out) -- not worth surfacing as a warning.
        const log = response?.error === 'No Supabase session available' ? console.log : console.warn;
        log(logPrefix, 'Known-words refresh did not complete:', response?.error);
      }
    },
  );
}

function combinedCleanDocument(doc: Document): Document {
  // Step 1: Remove elements with a fixed set of unwanted selectors.
  const unwantedSelectors: string[] = [
    'nav', 'aside', 'footer', 'header', 'form', 'iframe', 'script', 'style', 'noscript',
    '.advertisement', '.ad', '.sidebar', '.related', '.popup'
  ];
  unwantedSelectors.forEach((selector: string) => {
    doc.querySelectorAll(selector).forEach((el: Element) => el.remove());
  });

  // Step 2: Remove elements that likely belong to footer, privacy, or sitemap sections.
  const additionalSelectors: string[] = [
    '[class*="footer"]',
    '[id*="footer"]',
    '[class*="privacy"]',
    '[id*="privacy"]',
    '[class*="sitemap"]',
    '[id*="sitemap"]',
    '[id*="onetrust-consent-sdk"]',
    '[data-e2e*="recommendations-heading"]',
    '[class*="bbc-by8ykd"]'
  ];
  additionalSelectors.forEach((selector: string) => {
    doc.querySelectorAll(selector).forEach((el: Element) => el.remove());
  });

  return doc;
}

/**
 * Single router for messages this content script owns: article extraction
 * for the reader view, auth completion, and preference changes pushed from
 * the popup. Other message types (e.g. STORE_WORDS/GET_WORDS) also cross this
 * listener since chrome.runtime.sendMessage is extension-wide, but this
 * content script isn't their intended recipient, so they're ignored here.
 */
chrome.runtime.onMessage.addListener((message: ContentScriptMessage, sender, sendResponse) => {
  switch (message.type) {
    case 'EXTRACT_ARTICLE': {
      try {
        const docClone = document.cloneNode(true) as Document;
        const cleanedDoc = combinedCleanDocument(docClone);
        const reader = new Readability(cleanedDoc);
        const article = reader.parse();
        sendResponse({ article });
      } catch (error: unknown) {
        console.error('Error extracting article:', error);
        sendResponse({ error: getErrorMessage(error, 'Could not extract article') });
      }
      // Indicate an asynchronous response.
      return true;
    }

    case 'AUTH_SUCCESS': {
      sendCurrentPrefsToInjectedScripts();
      return;
    }

    case 'PREFS_UPDATED': {
      sendCurrentPrefsToInjectedScripts();
      return;
    }

    default:
      return;
  }
});

/**
 * Listen for logout events to clear the Supabase session.
 */
document.addEventListener('logout', () => {
  chrome.storage.local.remove('supabaseSession', () => {
    if (chrome.runtime.lastError) {
      console.error('Error deleting session:', chrome.runtime.lastError);
    } else {
      console.log('Session deleted successfully');
    }
  });
});

/**
 * Listen for preference changes.
 */
document.addEventListener('prefs', (event: CustomEvent<Prefs>) => {
  prefs = event.detail;
  console.log(logPrefix, 'Preferences updated:', prefs);
});

/**
 * Listen for messages from the translation popup.
 * This handles words that the user wants to add to their known words.
 */
window.addEventListener('message', (event) => {
  // PARTIAL MITIGATION -- read before relying on this.
  //
  // These checks only rule out forgery from *other frames*. The legitimate
  // sender (translationPopup.ts, reached from index.ts) is injected into this
  // page's MAIN world via a <script> tag, so it shares an origin and a window
  // with the host page's own scripts: for a hostile top-level page both
  // conditions below are satisfied, and it can still reach the privileged
  // ADD_WORD_TO_USERWORDS path. A shared nonce would not help either, since
  // anything handed to MAIN-world code is readable by the page.
  //
  // The actual fix is to stop running the trigger in the page's world --
  // siteApi.ts only uses DOM APIs (querySelector/pause/play/click), so
  // index.ts can move to the isolated world and this bridge can be deleted
  // outright. Tracked separately; do not treat this listener as trusted.
  if (event.source !== window || event.origin !== location.origin) {
    return;
  }

  const data = event.data;
  if (!data || typeof data !== 'object' || data.source !== 'translationPopup') {
    return;
  }

  // Two senders with two shapes: translationPopup.ts forwards the `data-id`
  // attribute (a string), while api-service.ts sends a parsed number. Accept
  // both and pass the value through untouched so the RPC payload is
  // unchanged -- but reject anything that is neither, which also drops the
  // "NaN" that a failed parseInt in markup.ts would otherwise send.
  const wordId = data.payload?.wordId;
  const isValidWordId =
    (typeof wordId === 'number' && Number.isInteger(wordId) && wordId > 0) ||
    (typeof wordId === 'string' && /^\d+$/.test(wordId));

  if (isValidWordId) {
    console.log('Received from translationPopup:', wordId);
    sendToBackground<{ success: boolean; error?: string }>(
      { type: 'ADD_WORD_TO_USERWORDS', wordId },
      (response) => {
        if (chrome.runtime.lastError) {
          console.error('Error adding word:', chrome.runtime.lastError);
          return;
        }
        if (!response?.success) {
          console.error('Error adding word:', response?.error);
        }
      },
    );
  } else {
    console.error('Invalid data received:', event.data.payload);
  }
});
