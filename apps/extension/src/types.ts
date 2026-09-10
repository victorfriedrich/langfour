import { Language } from './languages';
import type { BackendRequest, BackendResponse } from './messages';

export type ViewPopupEvent = {
  preferredLanguage: Language;
  host: string;
  isHidden: boolean;
  theme: 'dark' | 'light';
};

// Relays the isolated-world content script's known-words cache to the
// MAIN-world injected script, which has no chrome.storage/chrome.runtime
// access of its own.
export type KnownWordsEvent = {
  language: string;
  words: string[];
};

// Relays a backend call from a MAIN-world script (which has no
// chrome.runtime) to the content script, which forwards it to the
// background as a BACKEND_FETCH message and answers with the response event.
// `id` pairs the response with the request, since several can be in flight.
export type BackendRequestEvent = BackendRequest & { id: string };
export type BackendResponseEvent = { id: string; response: BackendResponse };
