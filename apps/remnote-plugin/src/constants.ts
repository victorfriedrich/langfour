// Must match the manifest's requiredScopes.
export const POWERUP = 'langfour_word';
export const SLOT_WORD_ID = 'wordId';
export const ROOT_DOC = 'Langfour';

export const SETTING_API_URL = 'api-url';
export const SETTING_DIRECTION = 'direction';
export const SETTING_INTERVAL = 'sync-interval-minutes';
export const SETTING_LINK_EXISTING = 'link-existing';

export const DEFAULT_API_URL = 'https://major-wynny-victorfriedrich-7c04e8cd.koyeb.app';

// Synced storage, so every device sees the last result and shares the token.
export const STORAGE_LAST_SYNC = 'last-sync';
export const STORAGE_TOKEN = 'token';
export const STORAGE_LANGUAGES = 'word-languages'; // word id -> language code
export const STORAGE_LAYOUT_VERSION = 'layout-version';

export const LANGUAGE_NAMES: Record<string, string> = {
  es: 'Spanish',
  de: 'German',
  it: 'Italian',
  fr: 'French',
};

export const DAY_MS = 86_400_000;
