/**
 * The one place the extension decides what a language is.
 *
 * The internal key is the ISO 639-1 code, matching `words.language`, the
 * `knownWords_<lang>` storage keys and every RPC argument.
 *
 * This replaces two things:
 *
 *  - `contentScript.determineLanguage()`, a switch that mapped ISO codes to
 *    English names, had no `'fr'` case, and fell through to
 *    `default: 'spanish'` — so a French learner was served Spanish words.
 *  - `preferencePopup/languages.ts`, a 95-entry table that existed only to
 *    type `Language` and happily accepted `mhr`.
 *
 * The popup also used to derive display names via `Intl.DisplayNames`, which
 * echoes its input back for an unrecognised-but-well-formed tag rather than
 * throwing. That is why a legacy `'spanish'` value rendered as a lowercase
 * "spanish" label next to a broken flag instead of failing loudly.
 */

export type Language = 'es' | 'de' | 'it' | 'fr';

export interface LanguageInfo {
  code: Language;
  /** English display name. Never sent to the database. */
  name: string;
  /** flagcdn.com identifier — a *country* code, hence not merged with `code`. */
  flag: string;
}

export const LANGUAGES: Record<Language, LanguageInfo> = {
  es: { code: 'es', name: 'Spanish', flag: 'es' },
  de: { code: 'de', name: 'German', flag: 'de' },
  it: { code: 'it', name: 'Italian', flag: 'it' },
  fr: { code: 'fr', name: 'French', flag: 'fr' },
};

export const LANGUAGE_LIST: LanguageInfo[] = Object.values(LANGUAGES);

const BY_NAME: Record<string, Language> = Object.fromEntries(
  LANGUAGE_LIST.map((l) => [l.name.toLowerCase(), l.code])
) as Record<string, Language>;

export function isLanguage(value: unknown): value is Language {
  return typeof value === 'string' && value in LANGUAGES;
}

/**
 * Accepts an ISO code or a legacy English name; returns null for anything
 * else. Null rather than a fallback, so an unrecognised value yields an empty
 * word list instead of quietly the wrong language.
 */
export function toLanguage(value: string | null | undefined): Language | null {
  if (!value) return null;
  const normalized = value.trim().toLowerCase();
  if (isLanguage(normalized)) return normalized;
  return BY_NAME[normalized] ?? null;
}

export function getLanguageInfo(value: string | null | undefined): LanguageInfo | null {
  const code = toLanguage(value);
  return code ? LANGUAGES[code] : null;
}
