// Rules for adding a practice result (apps/api/practice.py) to a card. No SDK
// import, so it runs in the unit tests.

export interface PracticeOutcome {
  outcome: 'again' | 'good';
}

/** Whether a result may be added to its card, judged on the live card: a
 *  wrong answer always, a right one only when the card is due. RemNote can't
 *  tell these reviews from its own, so a lucky answer in chat must not push a
 *  card weeks out. */
export function practiceVerdict(
  item: PracticeOutcome,
  card: { nextRepetitionTime?: number } | undefined,
  now: number,
): 'apply' | 'card_missing' | 'not_due' {
  if (!card) return 'card_missing';
  if (item.outcome === 'good' && card.nextRepetitionTime !== undefined && card.nextRepetitionTime > now) {
    return 'not_due';
  }
  return 'apply';
}
