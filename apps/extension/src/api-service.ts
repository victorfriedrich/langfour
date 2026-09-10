// Shared API helpers used by both reader.ts (extension page) and
// youtubeBookmark.ts (injected into the MAIN world of youtube.com pages).
// Plain ES exports instead of window.* globals, so each consumer's own
// Parcel bundle includes exactly what it imports rather than relying on a
// separate <script> tag having already run first.

import { debugLog } from './config';
import { BackendRequest, BackendResponse, sendToBackground } from './messages';
import { BackendRequestEvent, BackendResponseEvent } from './types';

// How long a MAIN-world caller waits for the content script relay before
// giving up. A plain fetch has no deadline either, but a relay with no
// listener would otherwise leave the promise pending forever.
const RELAY_TIMEOUT_MS = 30_000;

function relayFailure(statusText: string): BackendResponse {
  return { ok: false, status: 0, statusText, body: '' };
}

const pendingRelays = new Map<string, (response: BackendResponse) => void>();
let relayListenerInstalled = false;

function requestViaContentScript(request: BackendRequest): Promise<BackendResponse> {
  if (!relayListenerInstalled) {
    document.addEventListener('backend-response', ((event: CustomEvent<BackendResponseEvent>) => {
      const resolve = pendingRelays.get(event.detail.id);
      if (resolve) {
        pendingRelays.delete(event.detail.id);
        resolve(event.detail.response);
      }
    }) as EventListener);
    relayListenerInstalled = true;
  }

  return new Promise((resolve) => {
    const id = crypto.randomUUID();
    const timer = setTimeout(() => {
      if (pendingRelays.delete(id)) {
        resolve(relayFailure('Timed out waiting for the extension to answer'));
      }
    }, RELAY_TIMEOUT_MS);
    pendingRelays.set(id, (response) => {
      clearTimeout(timer);
      resolve(response);
    });
    const detail: BackendRequestEvent = { id, ...request };
    document.dispatchEvent(new CustomEvent<BackendRequestEvent>('backend-request', { detail }));
  });
}

/**
 * Every backend call goes through the background service worker, the only
 * context that can attach the Supabase bearer token the API requires.
 * Extension pages (reader.ts) message it directly. MAIN-world page scripts
 * (index.ts, youtubeBookmark.ts) have no chrome.runtime, so they relay
 * through contentScript.ts via CustomEvents on `document`, the same channel
 * the prefs and known-words caches already use. Passing a body makes it a
 * JSON POST; omitting it makes it a GET.
 */
export function requestBackend(path: string, body?: unknown): Promise<BackendResponse> {
  const request: BackendRequest =
    body === undefined ? { path, method: 'GET' } : { path, method: 'POST', body };

  if (typeof chrome !== 'undefined' && chrome.runtime?.id) {
    return new Promise((resolve) => {
      sendToBackground<BackendResponse | undefined>({ type: 'BACKEND_FETCH', ...request }, (response) => {
        if (chrome.runtime.lastError || !response) {
          resolve(relayFailure(chrome.runtime.lastError?.message ?? 'No response from background'));
          return;
        }
        resolve(response);
      });
    });
  }

  return requestViaContentScript(request);
}

// Parse article content using backend
export async function parseArticleWithBackend(articleContent: string, language: string) {
  try {
    debugLog('Sending parse request to:', '/parse');
    const response = await requestBackend('/parse', {
      text: articleContent,
      language: language
    });

    if (!response.ok) {
      throw new Error(`Error: ${response.statusText}`);
    }

    return JSON.parse(response.body);
  } catch (error) {
    console.error('Error parsing article:', error);
    return null;
  }
}

// Get translation for word
export async function fetchTranslation(word: string, language: string) {
  try {
    debugLog('Sending translation request for:', word);
    const response = await requestBackend('/api/translate-word', { word, language });

    if (!response.ok) {
      throw new Error(`Error: ${response.statusText}`);
    }

    const data = JSON.parse(response.body);
    return {
      id: parseInt(data.id),
      root: data.root,
      translation: data.translation,
    };
  } catch (error) {
    console.error('Translation error:', error);
    return null;
  }
}

// Save word to user's flashcards
export function saveWordToFlashcards(wordId: number) {
  window.postMessage({
    source: 'translationPopup',
    payload: { wordId }
  }, '*');
}

// Get translation for section
export async function translateSection(
  section: string,
  language: string,
): Promise<string | null> {
  try {
    debugLog('Sending section translation request');
    const response = await requestBackend('/api/translate', { section, language });

    if (!response.ok) {
      throw new Error(`Error: ${response.statusText}`);
    }

    const rawText = response.body;

    try {
      const data: unknown = JSON.parse(rawText);
      if (typeof data === 'string' && data.trim()) {
        return data;
      }
      if (typeof data === 'object' && data !== null) {
        if (
          'translation' in data &&
          typeof data.translation === 'string' &&
          data.translation.trim()
        ) {
          return data.translation;
        }

        const firstString = Object.values(data).find(
          (value): value is string =>
            typeof value === 'string' && value.trim().length > 0,
        );
        return firstString ?? null;
      }
    } catch {
      if (rawText.trim() && !rawText.includes('<!DOCTYPE html>')) {
        return rawText;
      }
    }

    return null;
  } catch (error) {
    console.error('Translation error:', error);
    return null;
  }
}

// Bookmark YouTube channel for indexing
export async function bookmarkChannel(channelId: string) {
  try {
    const response = await requestBackend('/youtube/bookmarks', { channel_id: channelId });
    if (!response.ok) {
      throw new Error(`Error: ${response.statusText}`);
    }
    return JSON.parse(response.body);
  } catch (error) {
    console.error('Bookmark channel error:', error);
    return null;
  }
}

// Check if a YouTube channel was already indexed
export async function checkChannelBookmarked(channelId: string) {
  try {
    const response = await requestBackend(`/youtube/bookmarks/${encodeURIComponent(channelId)}`);
    if (!response.ok) return { saved: false };
    return JSON.parse(response.body);
  } catch (error) {
    console.error('Check channel bookmarked error:', error);
    return { saved: false };
  }
}
