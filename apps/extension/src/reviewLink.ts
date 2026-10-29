import { WEB_URL } from './config';

// Reviews happen in RemNote when the user switched scheduling to it
// (userdata.review_provider, same as the web app's TodayCard). The link opens
// the notes of the language being learned (Langfour/Spanish), which the
// RemNote plugin reports; the Langfour document when that language has none,
// and RemNote's home page until the plugin has synced once.
const REM_ID = /^[A-Za-z0-9_-]{1,64}$/;
const remId = (value: unknown) => (typeof value === 'string' && REM_ID.test(value) ? value : null);

function remnoteUrl(rootRemId: unknown, languageRemIds: unknown, language: string | null) {
  const byLanguage = languageRemIds && typeof languageRemIds === 'object' ? (languageRemIds as Record<string, unknown>) : {};
  const id = (language && remId(byLanguage[language])) || remId(rootRemId);
  return id ? `https://www.remnote.com/document/${id}` : 'https://www.remnote.com/';
}

export function reviewLink(
  userdata: { review_provider?: unknown; remnote_root_rem_id?: unknown; remnote_language_rem_ids?: unknown } | null,
  language: string | null,
): {
  label: string;
  url: string;
} {
  return userdata?.review_provider === 'remnote'
    ? { label: 'Review in RemNote', url: remnoteUrl(userdata.remnote_root_rem_id, userdata.remnote_language_rem_ids, language) }
    : { label: 'Review flashcards', url: `${WEB_URL}/vocabulary` };
}
