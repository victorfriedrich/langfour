import type { BackendResponse } from './messages';

// The popup's row pointing at the Vocabulary page's "Words you likely know"
// (apps/web/src/app/vocabulary/stuck.ts). Shown while the list holds words
// the user hasn't been told about: all of them at first, then only words
// that joined since they last opened the link, such as ones that reached 10
// videos.

// The ids listed when the link was last opened. `true`, from before the
// seen-in-videos words, stands for the common ones that were listed then.
export const STUCK_OPENED_KEY = 'stuckWordsOpened';

export const stuckWordsUrl = (webUrl: string) => `${webUrl}/vocabulary?words=stuck`;

export function stuckWordsText(count: number): string {
  return count === 1
    ? '1 word you likely know is still marked learning'
    : `${count} words you likely know are still marked learning`;
}

type Listed = { word_id: number; reason?: 'common' | 'seen' };

export type StuckRow = {
  /** Every word the API lists, to remember when the link is opened. */
  listed: number[];
  /** How many of them the user hasn't been told about; 0 for no row. */
  fresh: number;
};

const NO_ROW: StuckRow = { listed: [], fresh: 0 };

function told(opened: unknown, word: Listed): boolean {
  if (opened === true) return word.reason !== 'seen';
  return Array.isArray(opened) && opened.includes(word.word_id);
}

/** What the row shows. Nothing when there are no new words or the API failed. */
export async function stuckWordsToShow(
  language: string,
  opened: () => Promise<unknown>,
  request: (path: string) => Promise<BackendResponse>,
): Promise<StuckRow> {
  const response = await request(`/api/vocabulary/stuck?language=${encodeURIComponent(language)}`);
  if (!response.ok) return NO_ROW;
  let words: Listed[];
  try {
    const body = JSON.parse(response.body) as { words?: unknown };
    if (!Array.isArray(body.words)) return NO_ROW;
    words = body.words as Listed[];
  } catch {
    return NO_ROW;
  }
  const previous = await opened();
  return {
    listed: words.map((w) => w.word_id),
    fresh: words.filter((w) => !told(previous, w)).length,
  };
}

/** What to store when the link is opened: everything listed now, and before. */
export function openedNow(previous: unknown, listed: number[]): number[] {
  return Array.from(new Set([...(Array.isArray(previous) ? (previous as number[]) : []), ...listed]));
}
