import { supabase, ensureSupabaseSession, getAccessToken } from './supabaseclient';
import { fetchWords } from './fetchWords';
import {
  ArticleData,
  ArticleExtractionResponse,
  assertNever,
  BackendRequest,
  BackendResponse,
  BackgroundMessage,
  sendToTab,
} from './messages';
import { getErrorMessage } from './errors';
import { BACKEND_URL, debugLog } from './config';
import { toLanguage } from './languages';

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

chrome.runtime.onMessage.addListener((message: BackgroundMessage, _sender, sendResponse) => {
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

    case 'ADD_WORD_TO_USERWORDS': {
      const { wordId } = message;
      addWordToUserwords(wordId).then(sendResponse);
      return true; // Keeps the message channel open for async response
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

function openReaderView(tabId: number): void {
  debugLog('Opening reader view for tab:', tabId);

  // First check if the tab exists
  chrome.tabs.get(tabId, () => {
    if (chrome.runtime.lastError) {
      console.error('Tab does not exist:', chrome.runtime.lastError);
      openReaderWithError('Tab does not exist');
      return;
    }

    requestArticleExtraction(tabId);
  });
}

function openReaderWithArticle(article: ArticleData): void {
  chrome.storage.local.set({ currentArticle: article }, () => {
    chrome.tabs.create({ url: chrome.runtime.getURL('src/reader.html') });
  });
}

// Supported subtitle sites load the content script declaratively. Reader mode
// also works on an arbitrary page the user explicitly invokes via the
// keyboard command; activeTab grants temporary access to inject it there.
// Try messaging first so supported sites are not injected twice -- content
// scripts share one JS realm per frame, and duplicate injection redeclares
// their top-level bindings.
function requestArticleExtraction(tabId: number): void {
  sendToTab<ArticleExtractionResponse>(tabId, { type: 'EXTRACT_ARTICLE' }, (response) => {
    if (chrome.runtime.lastError) {
      console.warn('Content script not responding, injecting and retrying:', chrome.runtime.lastError);
      chrome.scripting.executeScript({
        target: { tabId: tabId },
        files: ['src/contentScript.js']
      }, () => {
        if (chrome.runtime.lastError) {
          console.error('Could not inject content script:', chrome.runtime.lastError);
          extractArticleAsFallback(tabId);
          return;
        }

        // Give the freshly-injected content script a moment to initialize.
        setTimeout(() => {
          sendToTab<ArticleExtractionResponse>(tabId, { type: 'EXTRACT_ARTICLE' }, (retryResponse) => {
            if (chrome.runtime.lastError || !retryResponse?.article) {
              console.error('Could not communicate with content script after injection:', chrome.runtime.lastError);
              extractArticleAsFallback(tabId);
              return;
            }
            openReaderWithArticle(retryResponse.article);
          });
        }, 200);
      });
      return;
    }

    if (response && response.article) {
      openReaderWithArticle(response.article);
    } else {
      console.error('No article data received');
      openReaderWithError('Could not extract article content');
    }
  });
}

// Fallback extraction method using chrome.scripting
function extractArticleAsFallback(tabId: number): void {
  debugLog('Using fallback extraction method for tab:', tabId);

  // Execute script in the page to get the HTML content
  chrome.scripting.executeScript({
    target: { tabId: tabId },
    func: () => {
      // Simple extraction of page content
      const title = document.title;
      const content = document.body.innerText;
      return { title, content };
    }
  }, (results) => {
    if (chrome.runtime.lastError || !results || !results[0]) {
      console.error('Failed to extract using fallback:', chrome.runtime.lastError);
      openReaderWithError('Could not access page content');
      return;
    }

    const result = results[0].result as { title: string; content: string };
    debugLog('Extracted content using fallback:', result.title);

    // Send the raw content to the server for parsing
    backendFetch({
      path: '/parse',
      method: 'POST',
      body: {
        text: result.content,
        language: 'es' // Default language
      },
    })
    .then(response => {
      if (!response.ok) {
        throw new Error(`Error: ${response.statusText}`);
      }
      return JSON.parse(response.body);
    })
    .then(parsedArticle => {
      chrome.storage.local.set({ currentArticle: parsedArticle }, () => {
        chrome.tabs.create({ url: chrome.runtime.getURL('src/reader.html') });
      });
    })
    .catch(error => {
      console.error('Error parsing with backend:', error);
      // Still open reader, but with raw content
      chrome.storage.local.set({
        currentArticle: {
          title: result.title,
          content: result.content
        }
      }, () => {
        chrome.tabs.create({ url: chrome.runtime.getURL('src/reader.html') });
      });
    });
  });
}

// Helper to open reader with an error message
function openReaderWithError(errorMessage: string): void {
  chrome.storage.local.set({ 
    currentArticle: { 
      title: 'Error Extracting Content', 
      content: `Sorry, we couldn't extract the article content: ${errorMessage}.` 
    }
  }, () => {
    chrome.tabs.create({ url: chrome.runtime.getURL('src/reader.html') });
  });
}

// Update your command listener to use this function
chrome.commands.onCommand.addListener((command) => {
  if (command === 'toggle-reader') {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const activeTab = tabs[0];
      if (activeTab && activeTab.id) {
        openReaderView(activeTab.id);
      }
    });
  }
});
