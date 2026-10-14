// Shared message protocol between the background service worker, content
// scripts, and extension pages. Each sender should go through the typed
// helpers below so that a message with no matching handler is a compile
// error instead of a silent no-op.

import type { Session } from '@supabase/supabase-js';
import type { Language } from './languages';

export type ArticleData = {
  title?: string | null;
  content?: string | null;
  // Set by the content script; Readability's own fields where it has them.
  url?: string | null;
  siteName?: string | null;
  byline?: string | null;
};

export type ArticleExtractionResponse = {
  article?: ArticleData | null;
  error?: string;
};

export type DefaultLanguageResponse = {
  language?: Language;
  error?: string;
};

// A FastAPI backend call proxied through the background service worker. The
// backend rejects every request without a Supabase bearer token, and the
// background is the only context holding a Supabase client that can supply
// (and refresh) one, so no other context calls the backend directly.
export type BackendRequest = {
  path: string;
  method: 'GET' | 'POST';
  body?: unknown;
};

// Mirrors the parts of a fetch Response that cross the message bus. A
// transport failure (no session, network error, unknown path) is reported
// as `ok: false` with the reason in `statusText`, so callers handle it the
// same way as an HTTP error.
export type BackendResponse = {
  ok: boolean;
  status: number;
  statusText: string;
  body: string;
};

// Where the signed-in user stands with a word of a text, as classify_words
// (apps/api/sql/classify_words.sql) reports it. Tokens that are not
// vocabulary (names, acronyms, foreign words) get no entry at all.
export type WordStatus = 'new' | 'learning' | 'known' | 'ignored';
export type ClassifiedWord = { token: string; word_id: number; status: WordStatus };
export type ClassifyWordsResponse =
  | { ok: true; words: ClassifiedWord[] }
  | { ok: false; error: string };

// The user's history with one word, from word_progress
// (apps/api/sql/word_progress.sql). Timestamps are ISO strings.
export type WordProgress = {
  status: WordStatus;
  added_at: string | null;
  review_count: number;
  correct_count: number;
  last_reviewed_at: string | null;
  next_review_at: string | null;
};
export type WordProgressResponse =
  | { ok: true; progress: WordProgress | null }
  | { ok: false; error: string };

// The signed-in user as the reader's settings panel shows them. The review
// link goes to RemNote when the user schedules reviews there.
export type Account = {
  email: string;
  languages: Language[];
  language: Language | null;
  review: { label: string; url: string };
};
export type AccountResponse = { account: Account | null; error?: string };

// Messages the background service worker owns and handles.
export type BackgroundMessage =
  | { type: 'STORE_WORDS'; words: string[]; language: string }
  | { type: 'GET_WORDS'; language: string }
  | { type: 'GET_DEFAULT_LANGUAGE' }
  | { type: 'AUTH_SUCCESS'; session: Session }
  | { type: 'session' }
  | { type: 'view-popup' }
  | { type: 'OPEN_READER'; tabId: number }
  | { type: 'REFRESH_KNOWN_WORDS'; language: string }
  | { type: 'CLASSIFY_WORDS'; language: string; tokens: string[] }
  | { type: 'WORD_PROGRESS'; wordId: number }
  | { type: 'GET_ACCOUNT' }
  | { type: 'SET_LANGUAGE'; language: Language }
  | { type: 'SIGN_OUT' }
  // string | number is deliberate: translationPopup.ts forwards a `data-id`
  // attribute while api-service.ts sends a parsed integer, and both reach the
  // same RPC. Narrowing this to `string` would be a lie about the wire format.
  | { type: 'ADD_WORD_TO_USERWORDS'; wordId: string | number }
  | ({ type: 'BACKEND_FETCH' } & BackendRequest);

// Messages a content script owns and handles.
export type ContentScriptMessage =
  | { type: 'EXTRACT_ARTICLE' }
  | { type: 'AUTH_SUCCESS'; session?: Session }
  | { type: 'PREFS_UPDATED' };

export function sendToBackground<TResponse = unknown>(
  message: BackgroundMessage,
  callback?: (response: TResponse) => void,
): void {
  if (callback) {
    chrome.runtime.sendMessage(message, callback);
  } else {
    chrome.runtime.sendMessage(message);
  }
}

/**
 * Asks the background a read-only question and waits for the answer,
 * retrying when none comes. Safari on iOS stops the background worker
 * whenever it likes; a message that lands while it is stopped or restarting
 * can be answered with `undefined` (no lastError) or never answered, even
 * though the worker goes on to do the work. Only for messages that are safe
 * to repeat. Resolves `undefined` once every attempt has gone unanswered.
 */
export function askBackground<TResponse>(
  message: BackgroundMessage,
  { attempts = 3, timeoutMs = 10_000 } = {},
): Promise<TResponse | undefined> {
  const once = () =>
    new Promise<TResponse | undefined>((resolve) => {
      const timer = setTimeout(() => resolve(undefined), timeoutMs);
      chrome.runtime.sendMessage(message, (response: TResponse | undefined) => {
        clearTimeout(timer);
        if (chrome.runtime.lastError) {
          console.warn(`${message.type}: ${chrome.runtime.lastError.message}`);
        }
        resolve(response);
      });
    });

  return (async () => {
    for (let attempt = 1; attempt <= attempts; attempt++) {
      const response = await once();
      if (response !== undefined) return response;
      console.warn(`${message.type}: no answer from the background (attempt ${attempt} of ${attempts})`);
      if (attempt < attempts) await new Promise((r) => setTimeout(r, 300 * attempt));
    }
    return undefined;
  })();
}

export function sendToTab<TResponse = unknown>(
  tabId: number,
  message: ContentScriptMessage,
  callback?: (response: TResponse) => void,
): void {
  if (callback) {
    chrome.tabs.sendMessage(tabId, message, callback);
  } else {
    chrome.tabs.sendMessage(tabId, message);
  }
}

export function sendToActiveTab(message: ContentScriptMessage): void {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]?.id) {
      chrome.tabs.sendMessage(tabs[0].id, message);
    }
  });
}

// Compile-time exhaustiveness check for the background router, where the
// full set of senders is known. Only warns at runtime since this listener
// also shares the extension-wide chrome.runtime.onMessage bus.
export function assertNever(value: never): void {
  console.warn('Unhandled message reached assertNever:', value);
}
