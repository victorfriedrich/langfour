// What the progress views show, computed from review history. Pure
// functions, so they are testable without RemNote.
//
// A word is "learned" when every card of it was last answered correctly with
// a gap of 21 days or more before the next review, and is not far overdue:
// at most half that gap past its due date. A learned word counts as known
// everywhere in Langfour.
//
// The database computes the same rule in the view `user_known_words`
// (apps/api/sql/known_words.sql), which the recommender reads. Keep the two
// in step: LEARNED_DAYS and OVERDUE_GRACE have twins there.

import { DAY_MS } from './constants';

export interface Repetition {
  date: number;
  score: number;
  /** When the review was due; differs from `date` if done early or late. */
  scheduled?: number;
}

export interface CardLike {
  remId: string;
  nextRepetitionTime?: number;
  repetitionHistory?: Repetition[];
}

export interface WordCards {
  remId: string;
  wordId: number;
  root: string;
  language: string;
  cards: CardLike[];
}

export type Stage = 'new' | 'learning' | 'learned';
export const STAGES: Stage[] = ['new', 'learning', 'learned'];
export const LEARNED_DAYS = 21;
// A learned word may be this share of its gap overdue and still count.
export const OVERDUE_GRACE = 0.5;

// RemNote QueueInteractionScore: AGAIN 0, HARD 0.5, GOOD 1, EASY 1.5. The rest
// (too early, leech, reset, manual) are bookkeeping, not answers.
const GRADES = new Set([0, 0.5, 1, 1.5]);
const AGAIN = 0;

export function gradedReviews(card: CardLike): Repetition[] {
  return (card.repetitionHistory ?? [])
    .filter((r) => GRADES.has(r.score))
    .sort((a, b) => a.date - b.date);
}

interface Step {
  date: number;
  intervalDays: number;
  failed: boolean;
}

/** The interval each graded review gave the card: until the next review was
 *  due, or for the latest review, until the card's current due date. */
export function cardSteps(card: CardLike): Step[] {
  const reviews = gradedReviews(card);
  return reviews.map((review, i) => {
    const next = reviews[i + 1];
    const until = next ? next.scheduled ?? next.date : card.nextRepetitionTime ?? review.date;
    return { date: review.date, intervalDays: (until - review.date) / DAY_MS, failed: review.score === AGAIN };
  });
}

export function cardStageAt(card: CardLike, at: number): Stage {
  let last: Step | undefined;
  for (const step of cardSteps(card)) {
    if (step.date > at) break;
    last = step;
  }
  if (!last) return 'new';
  const overdue = at > last.date + last.intervalDays * (1 + OVERDUE_GRACE) * DAY_MS;
  return !last.failed && last.intervalDays >= LEARNED_DAYS && !overdue ? 'learned' : 'learning';
}

/** A word is as far along as its weakest card. */
export function wordStageAt(cards: CardLike[], at: number): Stage {
  if (cards.length === 0) return 'new';
  return cards
    .map((c) => cardStageAt(c, at))
    .reduce((a, b) => (STAGES.indexOf(a) <= STAGES.indexOf(b) ? a : b));
}

/** "Again" answers in the last `days`, across the word's cards. */
export function recentLapses(cards: CardLike[], now: number, days = 30): number {
  const since = now - days * DAY_MS;
  return cards.reduce(
    (n, c) => n + gradedReviews(c).filter((r) => r.score === AGAIN && r.date >= since).length,
    0,
  );
}

export interface WordRef {
  remId: string;
  root: string;
}

export interface Summary {
  words: number;
  stages: Record<Stage, number>;
  learnedLastWeek: number; // net change in learned words over 7 days
  trend: { day: number; learned: number }[]; // one point per day, oldest first
  newlyLearned: WordRef[]; // learned now, not a week ago
  slipping: (WordRef & { lapses: number })[]; // forgotten recently, not learned
}

function endOfDay(ms: number): number {
  const d = new Date(ms);
  d.setHours(23, 59, 59, 999);
  return d.getTime();
}

export function summarize(words: WordCards[], now: number, trendDays = 90): Summary {
  const stages: Record<Stage, number> = { new: 0, learning: 0, learned: 0 };
  const weekAgo = now - 7 * DAY_MS;
  const newlyLearned: WordRef[] = [];
  const slipping: Summary['slipping'] = [];

  // Day ends from oldest to today; today's point is "now".
  const days = Array.from({ length: trendDays }, (_, i) =>
    i === trendDays - 1 ? now : endOfDay(now - (trendDays - 1 - i) * DAY_MS),
  );
  const learnedPerDay = new Array(trendDays).fill(0);

  for (const word of words) {
    const stage = wordStageAt(word.cards, now);
    stages[stage] += 1;

    days.forEach((day, i) => {
      if (wordStageAt(word.cards, day) === 'learned') learnedPerDay[i] += 1;
    });

    if (stage === 'learned' && wordStageAt(word.cards, weekAgo) !== 'learned') {
      newlyLearned.push({ remId: word.remId, root: word.root });
    }
    const lapses = recentLapses(word.cards, now);
    if (stage !== 'learned' && lapses > 0) {
      slipping.push({ remId: word.remId, root: word.root, lapses });
    }
  }

  const weekAgoIndex = Math.max(0, trendDays - 8);
  return {
    words: words.length,
    stages,
    learnedLastWeek: stages.learned - learnedPerDay[weekAgoIndex],
    trend: days.map((day, i) => ({ day, learned: learnedPerDay[i] })),
    newlyLearned,
    slipping: slipping.sort((a, b) => b.lapses - a.lapses).slice(0, 12),
  };
}
