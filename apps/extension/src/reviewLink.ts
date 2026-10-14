import { WEB_URL } from './config';

// Reviews happen in RemNote when the user switched scheduling to it
// (userdata.review_provider, same as the web app's TodayCard). The link opens
// the review queue of their "Langfour" document, which the RemNote plugin
// reports; RemNote's home page until it has synced once.
const remnoteUrl = (rootRemId: unknown) =>
  typeof rootRemId === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(rootRemId)
    ? `https://www.remnote.com/flashcards/${rootRemId}`
    : 'https://www.remnote.com/';

export function reviewLink(userdata: { review_provider?: unknown; remnote_root_rem_id?: unknown } | null): {
  label: string;
  url: string;
} {
  return userdata?.review_provider === 'remnote'
    ? { label: 'Review in RemNote', url: remnoteUrl(userdata.remnote_root_rem_id) }
    : { label: 'Review flashcards', url: `${WEB_URL}/vocabulary` };
}
