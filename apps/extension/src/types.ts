import { Language } from './languages';

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
