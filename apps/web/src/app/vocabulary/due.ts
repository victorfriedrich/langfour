import { gradedReviews, type WordCards } from '../../../../remnote-plugin/src/stats';

/** Words with a review due by the end of today. Only cards that were
 *  answered at least once count: RemNote gives a new card a due date the
 *  moment it is created, so counting those would report every word not yet
 *  started as due (867 instead of 113 when this was written). New cards are
 *  introduced by RemNote at its own pace. */
export function wordsDueToday(words: WordCards[], now: number): number {
  const endOfToday = new Date(now).setHours(24, 0, 0, 0);
  return words.filter((w) =>
    w.cards.some((c) => c.nextRepetitionTime !== undefined && c.nextRepetitionTime < endOfToday && gradedReviews(c).length > 0),
  ).length;
}
