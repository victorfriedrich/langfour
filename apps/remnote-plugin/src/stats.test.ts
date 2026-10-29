import { describe, expect, it } from 'vitest';
import { DAY_MS } from './constants';
import { cardStageAt, overdueSince, recentLapses, summarize, wordStageAt, type CardLike, type WordCards } from './stats';

const NOW = new Date(2026, 8, 26, 15, 0).getTime();
const daysAgo = (n: number) => NOW - n * DAY_MS;

/** A card reviewed at the given days ago, each review answered `score`, with
 *  the next review due `dueInDays` after the last one. */
function card(reviews: [daysAgo: number, score: number][], dueInDays: number): CardLike {
  const history = reviews.map(([ago, score]) => ({ date: daysAgo(ago), score }));
  const last = history[history.length - 1];
  return {
    remId: 'r',
    repetitionHistory: history,
    nextRepetitionTime: last ? last.date + dueInDays * DAY_MS : undefined,
  };
}

function word(id: number, cards: CardLike[]): WordCards {
  return { remId: `rem-${id}`, wordId: id, root: `w${id}`, language: 'es', cards };
}

describe('cardStageAt', () => {
  it('is new until a graded review exists', () => {
    expect(cardStageAt(card([], 0), NOW)).toBe('new');
    expect(cardStageAt(card([[1, 0.01]], 3), NOW)).toBe('new'); // "too early" is not an answer
  });

  it('is learned once the interval reaches three weeks', () => {
    expect(cardStageAt(card([[2, 1]], 20), NOW)).toBe('learning');
    expect(cardStageAt(card([[2, 1]], 21), NOW)).toBe('learned');
  });

  it('is learning again once far overdue: past half its gap', () => {
    // Reviewed 40 days ago with a 30-day gap: due 10 days ago, grace 15 days.
    expect(cardStageAt(card([[40, 1]], 30), NOW)).toBe('learned');
    // Reviewed 60 days ago with a 30-day gap: due 30 days ago, past the grace.
    expect(cardStageAt(card([[60, 1]], 30), NOW)).toBe('learning');
  });

  it('is learning after a wrong answer, whatever the interval', () => {
    expect(cardStageAt(card([[2, 0]], 30), NOW)).toBe('learning');
  });

  it('reads the past from the gap each review was given', () => {
    // Reviewed 40 days ago, due again 10 days later; then 30 days ago with a
    // 25-day interval; then 5 days ago, forgotten.
    const c = card([[40, 1], [30, 1], [5, 0]], 1);
    expect(cardStageAt(c, daysAgo(35))).toBe('learning');
    expect(cardStageAt(c, daysAgo(10))).toBe('learned');
    expect(cardStageAt(c, NOW)).toBe('learning');
  });

  it('uses the scheduled date, not a late review, for the past interval', () => {
    const c: CardLike = {
      remId: 'r',
      repetitionHistory: [
        { date: daysAgo(60), score: 1 },
        { date: daysAgo(20), score: 1, scheduled: daysAgo(50) }, // 10-day interval, done late
      ],
      nextRepetitionTime: daysAgo(20) + 5 * DAY_MS,
    };
    expect(cardStageAt(c, daysAgo(30))).toBe('learning');
  });
});

it('a word is as far along as its weakest card', () => {
  expect(wordStageAt([card([[2, 1]], 30), card([[2, 1]], 3)], NOW)).toBe('learning');
  expect(wordStageAt([card([[2, 1]], 30), card([], 0)], NOW)).toBe('new');
  expect(wordStageAt([], NOW)).toBe('new');
});

describe('overdueSince', () => {
  it('is when the first card ran out of grace, if lateness alone keeps the word from learned', () => {
    // Due 30 days ago on a 30-day gap: grace ran out 15 days ago.
    expect(overdueSince([card([[60, 1]], 30), card([[2, 1]], 30)], NOW)).toBe(daysAgo(15));
  });

  it('is undefined while learned, or when a card is still learning or was failed', () => {
    expect(overdueSince([card([[40, 1]], 30)], NOW)).toBeUndefined();
    expect(overdueSince([card([[60, 1]], 30), card([[2, 1]], 3)], NOW)).toBeUndefined();
    expect(overdueSince([card([[60, 0]], 30)], NOW)).toBeUndefined();
    expect(overdueSince([], NOW)).toBeUndefined();
  });
});

it('counts only recent lapses', () => {
  expect(recentLapses([card([[60, 0], [10, 0], [5, 1], [2, 0]], 1)], NOW)).toBe(2);
});

describe('summarize', () => {
  const words = [
    word(1, [card([[40, 1], [30, 1]], 25)]), // learned for weeks
    word(2, [card([[20, 1], [3, 1]], 30)]), // learned 3 days ago
    word(3, [card([[10, 0], [4, 1]], 3)]), // slipping
    word(4, [card([], 0)]), // new
    word(5, [card([[50, 1]], 25)]), // learned until 12.5 days ago, review late
  ];
  const s = summarize(words, NOW);

  it('counts stages now', () => {
    expect(s.stages).toEqual({ new: 1, learning: 2, learned: 2 });
  });

  it('builds a daily trend that ends at today', () => {
    expect(s.trend).toHaveLength(90);
    expect(s.trend[89].learned).toBe(2);
    expect(s.trend[89 - 7].learned).toBe(1);
    expect(s.trend[0].learned).toBe(0);
    expect(s.learnedLastWeek).toBe(1);
  });

  it('lists words learned this week and words slipping', () => {
    expect(s.newlyLearned.map((w) => w.root)).toEqual(['w2']);
    expect(s.slipping).toEqual([{ remId: 'rem-3', root: 'w3', lapses: 1, lastLapse: daysAgo(10) }]);
  });

  it('lists words learned but for a late review', () => {
    expect(s.overdue).toEqual([{ remId: 'rem-5', root: 'w5', since: daysAgo(12.5) }]);
  });
});
