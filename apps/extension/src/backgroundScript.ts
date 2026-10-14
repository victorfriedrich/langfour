import { supabase, ensureSupabaseSession, getAccessToken } from './supabaseclient';
import { fetchWords } from './fetchWords';
import {
  ArticleData,
  ArticleExtractionResponse,
  assertNever,
  BackendRequest,
  BackendResponse,
  BackgroundMessage,
  ClassifiedWord,
  ClassifyWordsResponse,
  Account,
  AccountResponse,
  WordProgress,
  WordProgressResponse,
  sendToTab,
} from './messages';
import { getErrorMessage } from './errors';
import { BACKEND_URL, debugLog } from './config';
import { Language, toLanguage } from './languages';
import { reviewLink } from './reviewLink';
import { readerPageUrl, storeArticle, StoredArticle } from './readerArticles';

let sessionId: string | undefined;

// GoTrue rotates the refresh token on every refresh, and this worker's
// Supabase client holds its session in memory only. Without writing the
// refreshed session back, the next worker restart would replay the stale
// refresh token from storage, which GoTrue rejects as already used -- and
// ensureSupabaseSession would then discard the session as invalid.
supabase.auth.onAuthStateChange((event, session) => {
  if (event !== 'TOKEN_REFRESHED' || !session) return;

  // Only update a session that is still supposed to exist. Signing out
  // removes this key while this worker's client keeps its copy in memory, so
  // an unconditional write would let a later refresh put the credential back
  // and silently sign the user in again.
  chrome.storage.local.get('supabaseSession', (stored) => {
    if (!stored.supabaseSession) return;
    chrome.storage.local.set({ supabaseSession: session }, () => {
      if (chrome.runtime.lastError) {
        console.error('Error storing refreshed session:', chrome.runtime.lastError);
      }
    });
  });
});

function backendFailure(statusText: string, status = 0): BackendResponse {
  return { ok: false, status, statusText, body: '' };
}

/**
 * Calls the FastAPI backend with the current Supabase access token attached.
 * The backend's auth middleware is deny-by-default, so every call needs it.
 *
 * Callers are extension contexts, plus whatever contentScript.ts relays from
 * the MAIN world -- that relay checks the path before forwarding, so the
 * allowlist lives there, at the boundary, rather than being duplicated here.
 */
async function backendFetch({ path, method, body }: BackendRequest): Promise<BackendResponse> {
  let token: string | null;
  try {
    token = await getAccessToken();
  } catch (error: unknown) {
    console.error('Error ensuring Supabase session:', error);
    return backendFailure(getErrorMessage(error, 'Error ensuring Supabase session'));
  }
  if (!token) {
    return backendFailure('No Supabase session available', 401);
  }

  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
  }

  try {
    const response = await fetch(`${BACKEND_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    return {
      ok: response.ok,
      status: response.status,
      statusText: response.statusText,
      body: await response.text(),
    };
  } catch (error: unknown) {
    console.error('Backend request failed:', error);
    return backendFailure(getErrorMessage(error, 'Backend request failed'));
  }
}

/**
 * Uses the existing Supabase RPC function to fetch the user's last update timestamp.
 * This function returns an ISO string timestamp.
 */
async function fetchKnownWordsTimestamp(): Promise<string> {
  const { data, error } = await supabase.rpc('get_known_words_update_timestamp');
  if (error) {
    throw error;
  }
  // data is expected to be a timestamp (as string)
  return data as string;
}

/**
 * Checks the locally cached known words timestamp against the timestamp in
 * Supabase. If the server timestamp is newer (or no local timestamp
 * exists), refreshes the known-words cache. The background is the only
 * context that holds a Supabase client/session -- content scripts ask for
 * this via the REFRESH_KNOWN_WORDS message rather than calling Supabase
 * themselves.
 */
async function refreshKnownWordsIfStale(language: string): Promise<{ success: boolean; error?: string }> {
  // Namespaced per language, matching the `knownWords_<lang>` cache it guards.
  // As a single global key it went stale in two ways: switching language let
  // the old language's stamp suppress the new language's fetch, and the ISO
  // rename left every install with an empty `knownWords_es` that the stamp
  // left over from `knownWords_spanish` declared current. Keying the stamp to
  // the cache makes any future re-keying self-invalidating.
  const timestampKey = `knownWordsTimestamp_${language}`;
  const result = await chrome.storage.local.get([timestampKey, 'supabaseSession']);

  let hasSession: boolean;
  try {
    hasSession = await ensureSupabaseSession(result.supabaseSession);
  } catch (error: unknown) {
    console.error('Error ensuring Supabase session:', error);
    return {
      success: false,
      error: getErrorMessage(error, 'Error ensuring Supabase session'),
    };
  }
  if (!hasSession) {
    return { success: false, error: 'No Supabase session available' };
  }

  const localTimestamp: Date | null = result[timestampKey]
    ? new Date(result[timestampKey])
    : null;

  try {
    const serverTimestampStr = await fetchKnownWordsTimestamp();
    const serverTimestamp = new Date(serverTimestampStr);

    // Refresh cache if no local timestamp or if server timestamp is more recent.
    if (!localTimestamp || serverTimestamp > localTimestamp) {
      debugLog('Cache is outdated. Refreshing known words...');
      const words = await fetchWords(language);
      const wordsArray = Array.from(words);
      await chrome.storage.local.set({
        [`knownWords_${language}`]: wordsArray,
        [timestampKey]: serverTimestamp.toISOString(),
      });
      debugLog(`Successfully stored ${wordsArray.length} ${language} words`);
    } else {
      debugLog('Cache is current.');
    }
    return { success: true };
  } catch (error: unknown) {
    console.error('Error checking or updating cache:', error);
    return {
      success: false,
      error: getErrorMessage(error, 'Error checking or updating cache'),
    };
  }
}

/**
 * Add a word to the user's known words list via Supabase RPC call.
 */
async function addWordToUserwords(wordId: string | number): Promise<{ success: boolean; error?: string }> {
  const result = await chrome.storage.local.get('supabaseSession');
  const hasSession = await ensureSupabaseSession(result.supabaseSession);
  if (!hasSession) {
    return { success: false, error: 'No Supabase session available' };
  }

  try {
    const { error } = await supabase.rpc('move_words_to_userwords', {
      _word_ids: [wordId]
    });

    if (error) {
      console.error('Supabase error:', error);
      return { success: false, error: error.message };
    }

    return { success: true };
  } catch (err: unknown) {
    console.error('Error adding words to userwords:', err);
    return {
      success: false,
      error: getErrorMessage(err, 'Error adding words to userwords'),
    };
  }
}

// Tokens per classify_words call; an article has a few hundred to a couple
// of thousand distinct ones.
const CLASSIFY_BATCH_SIZE = 1000;

/**
 * Which tokens of a text are vocabulary, and the user's status for each.
 * The dictionary decides what counts as a word (names and acronyms are
 * marked invalid there), and user_known_words decides what "known" means,
 * so the reader no longer guesses either from spelling.
 */
async function classifyWords(language: string, tokens: string[]): Promise<ClassifyWordsResponse> {
  const { supabaseSession } = await chrome.storage.local.get('supabaseSession');
  if (!(await ensureSupabaseSession(supabaseSession))) {
    return { ok: false, error: 'No Supabase session available' };
  }

  const words: ClassifiedWord[] = [];
  for (let start = 0; start < tokens.length; start += CLASSIFY_BATCH_SIZE) {
    const { data, error } = await supabase.rpc('classify_words', {
      language_filter: language,
      tokens: tokens.slice(start, start + CLASSIFY_BATCH_SIZE),
    });
    if (error) {
      console.error('classify_words failed:', error);
      return { ok: false, error: error.message };
    }
    words.push(...((data ?? []) as ClassifiedWord[]));
  }
  return { ok: true, words };
}

/** The user's history with one word, for the reader's word sheet. */
async function wordProgress(wordId: number): Promise<WordProgressResponse> {
  const { supabaseSession } = await chrome.storage.local.get('supabaseSession');
  if (!(await ensureSupabaseSession(supabaseSession))) {
    return { ok: false, error: 'No Supabase session available' };
  }
  const { data, error } = await supabase.rpc('word_progress', { word_id_param: wordId });
  if (error) {
    console.error('word_progress failed:', error);
    return { ok: false, error: error.message };
  }
  return { ok: true, progress: ((data ?? []) as WordProgress[])[0] ?? null };
}

/** Who is signed in, for the reader's settings panel. null when nobody is. */
async function getAccount(): Promise<AccountResponse> {
  const { supabaseSession } = await chrome.storage.local.get('supabaseSession');
  if (!(await ensureSupabaseSession(supabaseSession))) return { account: null };
  const { data: { session } } = await supabase.auth.getSession();
  if (!session) return { account: null };

  const [languages, language, userdata] = await Promise.all([
    supabase.rpc('get_available_languages'),
    supabase.rpc('get_user_default_language'),
    supabase.from('userdata').select('review_provider, remnote_root_rem_id').eq('user_id', session.user.id).maybeSingle(),
  ]);
  for (const { error } of [languages, language, userdata]) {
    if (error) console.error('Could not load account details:', error);
  }
  const available = Array.isArray(languages.data)
    ? [...new Set(languages.data.map((lang: string) => toLanguage(lang)).filter((lang): lang is Language => lang !== null))]
    : [];
  const account: Account = {
    email: session.user.email ?? '',
    languages: available,
    language: toLanguage(typeof language.data === 'string' ? language.data : null),
    review: reviewLink(userdata.data),
  };
  return { account };
}

async function setLanguage(language: Language): Promise<{ ok: boolean; error?: string }> {
  const { supabaseSession } = await chrome.storage.local.get('supabaseSession');
  if (!(await ensureSupabaseSession(supabaseSession))) return { ok: false, error: 'Not signed in' };
  const { error } = await supabase.rpc('set_user_default_language', { _language: language });
  return error ? { ok: false, error: error.message } : { ok: true };
}

/**
 * Signs out this worker's client and drops the stored session it would
 * otherwise rehydrate from on its next wake-up. Extension pages also keep a
 * copy in their own localStorage, which only a page can clear.
 */
async function signOut(): Promise<{ ok: boolean }> {
  const { error } = await supabase.auth.signOut();
  if (error) console.error('Error signing out:', error);
  // Even a failed request may have revoked the session server-side.
  await chrome.storage.local.remove('supabaseSession');
  return { ok: true };
}

chrome.runtime.onMessage.addListener((message: BackgroundMessage, sender, sendResponse) => {
  debugLog('Background script received message:', message.type);

  switch (message.type) {
    // Store words in chrome.storage.local
    case 'STORE_WORDS': {
      const { words, language } = message;
      debugLog(`Storing ${words.length} ${language} words in storage`);

      chrome.storage.local.set({
        [`knownWords_${language}`]: words
      }, () => {
        if (chrome.runtime.lastError) {
          console.error('Error storing words:', chrome.runtime.lastError);
          sendResponse({ success: false, error: chrome.runtime.lastError.message });
        } else {
          debugLog(`Successfully stored ${words.length} ${language} words`);
          sendResponse({ success: true });
        }
      });
      return true; // Important: Keeps the message channel open for async response
    }

    // Retrieve words from chrome.storage.local
    case 'GET_WORDS': {
      const { language } = message;
      debugLog(`Getting ${language} words from storage`);

      chrome.storage.local.get(`knownWords_${language}`, (result) => {
        const words = result[`knownWords_${language}`] || [];
        debugLog(`Retrieved ${words.length} ${language} words from storage`);
        sendResponse({ words });
      });
      return true; // Important: Keeps the message channel open for async response
    }

    case 'GET_DEFAULT_LANGUAGE': {
      chrome.storage.local.get('supabaseSession', async (result) => {
        try {
          const hasSession = await ensureSupabaseSession(result.supabaseSession);
          if (!hasSession) {
            sendResponse({ error: 'No Supabase session available' });
            return;
          }

          const { data, error } = await supabase.rpc('get_user_default_language');
          if (error) {
            console.error('Supabase RPC error:', error);
            sendResponse({ error: error.message });
            return;
          }

          const language = toLanguage(typeof data === 'string' ? data : null);
          if (!language) {
            sendResponse({ error: 'No valid default language returned' });
            return;
          }

          sendResponse({ language });
        } catch (error: unknown) {
          console.error('Could not fetch default language:', error);
          sendResponse({
            error: getErrorMessage(error, 'Could not fetch default language'),
          });
        }
      });

      return true; // Keeps the response channel open
    }

    case 'AUTH_SUCCESS': {
      debugLog('Received AUTH_SUCCESS message');

      // Store the session data in chrome.storage.local
      chrome.storage.local.set({ supabaseSession: message.session }, () => {
        if (chrome.runtime.lastError) {
          console.error('Error storing session:', chrome.runtime.lastError);
        } else {
          debugLog('Session stored successfully');
        }
      });

      // Optionally, you can send a response back to the auth handler
      sendResponse({ status: 'received' });
      return;
    }

    case 'session': {
      sessionId = crypto.randomUUID();
      return;
    }

    case 'view-popup': {
      if (!sessionId) {
        sessionId = crypto.randomUUID();
      }
      return;
    }

    case 'REFRESH_KNOWN_WORDS': {
      const { language } = message;
      refreshKnownWordsIfStale(language).then(sendResponse);
      return true; // Keeps the message channel open for async response
    }

    case 'CLASSIFY_WORDS': {
      classifyWords(message.language, message.tokens)
        .catch((error): ClassifyWordsResponse => ({ ok: false, error: getErrorMessage(error, 'Lookup failed') }))
        .then(sendResponse);
      return true; // Keeps the message channel open for async response
    }

    case 'GET_ACCOUNT': {
      getAccount()
        .catch((error): AccountResponse => ({ account: null, error: getErrorMessage(error, 'Could not load the account') }))
        .then(sendResponse);
      return true; // Keeps the message channel open for async response
    }

    case 'SET_LANGUAGE': {
      setLanguage(message.language)
        .catch((error) => ({ ok: false, error: getErrorMessage(error, 'Could not change the language') }))
        .then(sendResponse);
      return true; // Keeps the message channel open for async response
    }

    case 'SIGN_OUT': {
      signOut().then(sendResponse);
      return true; // Keeps the message channel open for async response
    }

    case 'WORD_PROGRESS': {
      wordProgress(message.wordId)
        .catch((error): WordProgressResponse => ({ ok: false, error: getErrorMessage(error, 'Lookup failed') }))
        .then(sendResponse);
      return true; // Keeps the message channel open for async response
    }

    case 'ADD_WORD_TO_USERWORDS': {
      const { wordId } = message;
      addWordToUserwords(wordId).then(sendResponse);
      return true; // Keeps the message channel open for async response
    }

    case 'OPEN_READER': {
      // Only the popup asks for this. A content script has no business
      // pointing the reader (and its script injection) at another tab.
      if (sender.tab) return;
      // Answer once the reader is on its way, so the popup can show progress
      // until then instead of closing on a tab that seems to do nothing.
      readerOpened.set(message.tabId, () => sendResponse({ opened: true }));
      openReaderView(message.tabId, 'replace');
      return true;
    }

    case 'BACKEND_FETCH': {
      const { path, method, body } = message;
      backendFetch({ path, method, body }).then(sendResponse);
      return true; // Keeps the message channel open for async response
    }

    default:
      assertNever(message);
      return;
  }
});

// Where the reader opens. The popup replaces the page it was opened on, like
// Safari's own Reader: Back returns to the article, which on iOS is the only
// natural way out. The keyboard command keeps opening a new tab.
type ReaderPlacement = 'replace' | 'new-tab';

function openReaderView(tabId: number, placement: ReaderPlacement): void {
  debugLog('Opening reader view for tab:', tabId);

  chrome.tabs.get(tabId, (tab) => {
    if (chrome.runtime.lastError || !tab) {
      console.error('Tab does not exist:', chrome.runtime.lastError);
      void showReader({ title: 'Could not open the reader', content: 'The page was closed before it could be read.', error: true }, tabId, 'new-tab');
      return;
    }

    requestArticleExtraction(tab, placement);
  });
}

// Popup callbacks waiting for "the reader is opening", keyed by tab.
const readerOpened = new Map<number, () => void>();

async function showReader(article: Omit<StoredArticle, 'savedAt'>, tabId: number, placement: ReaderPlacement): Promise<void> {
  const url = readerPageUrl(await storeArticle(article));
  readerOpened.get(tabId)?.();
  readerOpened.delete(tabId);
  if (placement === 'replace') {
    try {
      await chrome.tabs.update(tabId, { url });
      return;
    } catch (error) {
      console.warn('Could not open the reader in place, using a new tab:', error);
    }
  }
  await chrome.tabs.create({ url });
}

function withSource(article: ArticleData, tab: chrome.tabs.Tab): Omit<StoredArticle, 'savedAt'> {
  return { ...article, url: article.url ?? tab.url ?? null };
}

// Supported subtitle sites load the content script declaratively. Reader mode
// also works on an arbitrary page the user explicitly invokes via the popup
// or the keyboard command; activeTab grants temporary access to inject it
// there. Try messaging first so supported sites are not injected twice --
// content scripts share one JS realm per frame, and duplicate injection
// redeclares their top-level bindings.
function requestArticleExtraction(tab: chrome.tabs.Tab, placement: ReaderPlacement): void {
  const tabId = tab.id!;
  sendToTab<ArticleExtractionResponse>(tabId, { type: 'EXTRACT_ARTICLE' }, (response) => {
    // Chrome reports a tab without our content script through lastError;
    // Safari just answers undefined. A loaded script always answers with an
    // object, even when Readability finds nothing.
    if (chrome.runtime.lastError || response === undefined) {
      console.warn('Content script not responding, injecting and retrying:', chrome.runtime.lastError);
      chrome.scripting.executeScript({
        target: { tabId: tabId },
        files: ['src/contentScript.js']
      }, () => {
        if (chrome.runtime.lastError) {
          console.error('Could not inject content script:', chrome.runtime.lastError);
          void showReader({
            title: 'Langfour cannot read this page',
            content: 'The browser does not let extensions read this page. Pages like the start page, settings and other extensions are off limits.',
            url: tab.url ?? null,
            error: true,
          }, tabId, placement);
          return;
        }

        // Give the freshly-injected content script a moment to initialize.
        setTimeout(() => {
          sendToTab<ArticleExtractionResponse>(tabId, { type: 'EXTRACT_ARTICLE' }, (retryResponse) => {
            if (chrome.runtime.lastError || retryResponse === undefined) {
              console.error('Could not communicate with content script after injection:', chrome.runtime.lastError);
              void showReader({
          title: 'Langfour cannot read this page',
          content: 'The browser does not let extensions read this page. Pages like the start page, settings and other extensions are off limits.',
          url: tab.url ?? null,
          error: true,
        }, tabId, placement);
              return;
            }
            showExtracted(retryResponse, tab, placement);
          });
        }, 200);
      });
      return;
    }

    showExtracted(response, tab, placement);
  });
}

function showExtracted(response: ArticleExtractionResponse, tab: chrome.tabs.Tab, placement: ReaderPlacement): void {
  if (response.article) {
    void showReader(withSource(response.article, tab), tab.id!, placement);
    return;
  }
  if (response.error) console.error('Article extraction failed:', response.error);
  void showReader({
    title: 'This page has no article to read',
    content: 'Langfour could not find a main text on this page. Try it on a news article or blog post.',
    url: tab.url ?? null,
    error: true,
  }, tab.id!, placement);
}

// First run: send new users to the sign-in page with a short how-to.
// The Safari build skips this: there the popup is the whole sign-in flow
// (email, then the code), and a tab opening on its own after install was
// one screen too many.
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === 'install' && process.env.EXTENSION_TARGET !== 'safari') {
    chrome.tabs.create({ url: chrome.runtime.getURL('src/auth.html?welcome=1') });
  }
});

// The Safari build has no popup (scripts/build-safari.mjs), so tapping
// Langfour in Safari's menu lands here and opens the reader straight away,
// in place, like Safari's own Reader. Account and language live in the
// reader's settings panel. Chrome keeps its popup, where this never fires.
chrome.action.onClicked.addListener((tab) => {
  if (tab.id !== undefined) openReaderView(tab.id, 'replace');
});

// Safari on iOS has no commands API, and a top-level throw here would stop
// the whole service worker from registering. The popup's reader button is
// the entry point there.
chrome.commands?.onCommand.addListener((command) => {
  if (command === 'toggle-reader') {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const activeTab = tabs[0];
      if (activeTab && activeTab.id) {
        openReaderView(activeTab.id, 'new-tab');
      }
    });
  }
});
