import type { BackendResponse } from './messages';

// The popup's one-time row pointing at the Vocabulary page's "Words you likely
// know" (apps/web/src/app/vocabulary/stuck.ts). Shown while there are such
// words, until the user opens the link once.

export const STUCK_OPENED_KEY = 'stuckWordsOpened';

export const stuckWordsUrl = (webUrl: string) => `${webUrl}/vocabulary?words=stuck`;

export function stuckWordsText(count: number): string {
  return count === 1
    ? '1 word you likely know is still marked learning'
    : `${count} words you likely know are still marked learning`;
}

/** How many to show, or 0 for no row: already opened, none, or the API failed. */
export async function stuckWordsToShow(
  language: string,
  opened: () => Promise<boolean>,
  request: (path: string) => Promise<BackendResponse>,
): Promise<number> {
  if (await opened()) return 0;
  const response = await request(`/api/vocabulary/stuck?language=${encodeURIComponent(language)}`);
  if (!response.ok) return 0;
  try {
    const { words } = JSON.parse(response.body) as { words?: unknown[] };
    return Array.isArray(words) ? words.length : 0;
  } catch {
    return 0;
  }
}
