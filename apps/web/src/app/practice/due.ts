import { gradedReviews, type WordCards } from '../../../../remnote-plugin/src/stats';

/** What RemNote's queue holds today, in its own unit: cards. */
export interface DueCards {
  /** Answered before, due again by the end of today. */
  reviews: number;
  /** Never answered. RemNote gives a card a due date the moment it is created
   *  and puts it in the same queue, so the user sees these too. */
  new: number;
}

/** A word whose cards the plugin turned off: known, and never answered
 *  (pauseKnown in apps/remnote-plugin/src/sync.ts). RemNote leaves them out. */
const turnedOff = (word: WordCards & { status?: string }) =>
  word.status === 'known' && !word.cards.some((c) => gradedReviews(c).length > 0);

/** The cards RemNote will show as due today, counted as it counts them: one
 *  per card (a word has a card each way), new cards included, cards turned
 *  off for known words left out. Counting words with an answered card instead
 *  showed 175 here while RemNote showed about 1,000. */
export function cardsDueToday(words: (WordCards & { status?: string })[], now: number): DueCards {
  const endOfToday = new Date(now).setHours(24, 0, 0, 0);
  const due: DueCards = { reviews: 0, new: 0 };
  for (const word of words) {
    if (turnedOff(word)) continue;
    for (const card of word.cards) {
      if (card.nextRepetitionTime === undefined || card.nextRepetitionTime >= endOfToday) continue;
      if (gradedReviews(card).length > 0) due.reviews += 1;
      else due.new += 1;
    }
  }
  return due;
}

/** "179 reviews and 766 new cards", for the count's hover text. */
export function dueBreakdown({ reviews, new: fresh }: DueCards): string {
  const n = (count: number, one: string, many: string) => `${count.toLocaleString()} ${count === 1 ? one : many}`;
  return `${n(reviews, 'review', 'reviews')} and ${n(fresh, 'new card', 'new cards')}`;
}
