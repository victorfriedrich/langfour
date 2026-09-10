// Shared message protocol between the background service worker, content
// scripts, and extension pages. Each sender should go through the typed
// helpers below so that a message with no matching handler is a compile
// error instead of a silent no-op.

import type { Session } from '@supabase/supabase-js';
import type { Language } from './languages';

export type ArticleData = {
  title?: string | null;
  content?: string | null;
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

// Messages the background service worker owns and handles.
export type BackgroundMessage =
  | { type: 'STORE_WORDS'; words: string[]; language: string }
  | { type: 'GET_WORDS'; language: string }
  | { type: 'GET_DEFAULT_LANGUAGE' }
  | { type: 'AUTH_SUCCESS'; session: Session }
  | { type: 'session' }
  | { type: 'view-popup' }
  | { type: 'REFRESH_KNOWN_WORDS'; language: string }
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
