// Rules for adding a practice result (apps/api/practice.py) to a card. No SDK
// import, so it runs in the unit tests.

export interface PracticeOutcome {
  outcome: 'again' | 'good';
}

/** Whether a result may be added to its card, judged on the live card and
 *  Rem: never while the Rem's flashcards are turned off; a wrong answer
 *  always; a right one only when the card is due. RemNote can't tell these
 *  reviews from its own, so a lucky answer in chat must not push a card weeks
 *  out. */
export function practiceVerdict(
  item: PracticeOutcome,
  card: { nextRepetitionTime?: number } | undefined,
  practiced: boolean,
  now: number,
): 'apply' | 'card_missing' | 'practice_off' | 'not_due' {
  if (!card) return 'card_missing';
  if (!practiced) return 'practice_off';
  if (item.outcome === 'good' && card.nextRepetitionTime !== undefined && card.nextRepetitionTime > now) {
    return 'not_due';
  }
  return 'apply';
}

/** The date of the review added to a card that had `count` reviews before, or
 *  undefined if none was added. A review the user made in between would be
 *  taken for it, which errs towards not adding one twice. */
export function reviewAddedSince(count: number, history: { date: number }[]): number | undefined {
  return history.length > count ? history[history.length - 1].date : undefined;
}
