/**
 * The one place the web app decides what a language is.
 *
 * The internal key is the ISO 639-1 code, matching `words.language` and every
 * RPC argument. English names are for display only.
 *
 * Before this existed, eight hooks reached the database by sending
 * `language.name.toLowerCase()` — depending on the *display name* happening to
 * equal the database key. That coupling is why renaming a language in the UI
 * would have silently returned zero rows.
 */

export type LanguageCode = 'es' | 'de' | 'it' | 'fr';

export interface Language {
  code: LanguageCode;
  /** English display name. Never sent to the database. */
  name: string;
  /** flagcdn.com identifier — a *country* code, which is why it is stored
   *  separately rather than reusing `code`. */
  flag: string;
}

export const LANGUAGES: Record<LanguageCode, Language> = {
  es: { code: 'es', name: 'Spanish', flag: 'es' },
  de: { code: 'de', name: 'German', flag: 'de' },
  it: { code: 'it', name: 'Italian', flag: 'it' },
  fr: { code: 'fr', name: 'French', flag: 'fr' },
};

export const LANGUAGE_LIST: Language[] = Object.values(LANGUAGES);

const BY_NAME: Record<string, LanguageCode> = Object.fromEntries(
  LANGUAGE_LIST.map((l) => [l.name.toLowerCase(), l.code])
) as Record<string, LanguageCode>;

export function isLanguageCode(value: unknown): value is LanguageCode {
  return typeof value === 'string' && value in LANGUAGES;
}

/**
 * Accepts an ISO code or a legacy English name; returns null for anything else.
 *
 * Null rather than a fallback on purpose: an unrecognised value should produce
 * an empty result, not silently the wrong language.
 */
export function toLanguageCode(value: string | null | undefined): LanguageCode | null {
  if (!value) return null;
  const normalized = value.trim().toLowerCase();
  if (isLanguageCode(normalized)) return normalized;
  return BY_NAME[normalized] ?? null;
}

export function getLanguage(value: string | null | undefined): Language | null {
  const code = toLanguageCode(value);
  return code ? LANGUAGES[code] : null;
}
