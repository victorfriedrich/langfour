import { Language, toLanguage } from '../languages';
import { DefaultLanguageResponse, sendToBackground } from '../messages';

export type Prefs = {
  preferredLanguage: Language;
};

// Fallback if the backend call fails
export const defaultPrefs: Prefs = {
  preferredLanguage: 'es'
};

const preferredLanguageKey = 'preferredLanguage';
const preferredLanguageResolvedKey = 'preferredLanguageResolved';

function getBackendDefaultLanguage(): Promise<Language | null> {
  return new Promise((resolve) => {
    sendToBackground<DefaultLanguageResponse>({ type: 'GET_DEFAULT_LANGUAGE' }, (response) => {
      const language = toLanguage(response?.language);
      if (chrome.runtime.lastError || !language) {
        console.warn(
          'Could not fetch default language from background:',
          chrome.runtime.lastError?.message || response?.error,
        );
        resolve(null);
      } else {
        resolve(language);
      }
    });
  });
}

export function getPrefs(callback: (prefs: Prefs) => void) {
  chrome.storage.sync.get(
    [preferredLanguageKey, preferredLanguageResolvedKey],
    (result) => {
      const storedLanguage = toLanguage(result[preferredLanguageKey]);

      // Preferences written by this version are trusted immediately. Older
      // values are re-checked against the account once so installs that
      // previously persisted the transient Spanish fallback can self-heal.
      if (storedLanguage && result[preferredLanguageResolvedKey] === true) {
        callback({ preferredLanguage: storedLanguage });
        return;
      }

      getBackendDefaultLanguage().then((backendLanguage) => {
        if (backendLanguage) {
          setPrefs({ preferredLanguage: backendLanguage }, () => {
            callback({ preferredLanguage: backendLanguage });
          });
          return;
        }

        // A missing session or temporary backend failure must not become a
        // durable Spanish preference. Keep a valid legacy value in memory if
        // one exists; otherwise use the product default for this invocation.
        callback({
          preferredLanguage: storedLanguage ?? defaultPrefs.preferredLanguage,
        });
      });
    },
  );
}

export function setPrefs(prefs: Prefs, callback: () => void) {
  chrome.storage.sync.set(
    {
      [preferredLanguageKey]: prefs.preferredLanguage,
      [preferredLanguageResolvedKey]: true,
    },
    callback,
  );
}
