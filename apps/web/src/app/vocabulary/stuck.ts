/** A learning word among the most common ones that was never reviewed
 *  (GET /api/vocabulary/stuck). */
export interface StuckWord {
  word_id: number;
  word: string;
  translation: string | null;
  videos: number; // videos its captions were seen in
  lookups: number;
}

/** The tab's link, from the extension popup too. */
export const STUCK_PARAM = 'words';
export const STUCK_VALUE = 'stuck';

/** Ticked to start with: all but the words the user looked up, which they
 *  may not know yet. */
export function preselected(words: StuckWord[]): number[] {
  return words.filter((w) => w.lookups === 0).map((w) => w.word_id);
}

/** "in 12 videos, looked up 3×", or nothing when there is no evidence. */
export function evidence(word: StuckWord): string {
  const parts: string[] = [];
  if (word.videos > 0) parts.push(`in ${word.videos.toLocaleString()} ${word.videos === 1 ? 'video' : 'videos'}`);
  if (word.lookups > 0) parts.push(`looked up ${word.lookups.toLocaleString()}×`);
  return parts.join(', ');
}
