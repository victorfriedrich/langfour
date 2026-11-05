import { describe, expect, it } from 'vitest';
import type { CardLike, WordCards } from '../../../../remnote-plugin/src/stats';
import { cardsDueToday, dueBreakdown } from './due';

const NOW = new Date(2026, 9, 2, 12).getTime(); // noon, local time
const HOUR = 3_600_000;

const word = (...cards: CardLike[]): WordCards & { status: string } =>
  ({ remId: 'r', wordId: 1, root: 'x', language: 'es', status: 'learning', cards });
const known = (...cards: CardLike[]) => ({ ...word(...cards), status: 'known' });
const card = (due: number | undefined, scores: number[] = []): CardLike => ({
  remId: 'r',
  nextRepetitionTime: due,
  repetitionHistory: scores.map((score, i) => ({ date: NOW - (i + 1) * 24 * HOUR, score })),
});

describe('cardsDueToday', () => {
  it('counts an answered card due today or overdue as a review', () => {
    expect(cardsDueToday([word(card(NOW + 3 * HOUR, [1])), word(card(NOW - 48 * HOUR, [0]))], NOW)).toEqual({ reviews: 2, new: 0 });
  });

  it('counts a new card, since RemNote queues it with the rest', () => {
    expect(cardsDueToday([word(card(NOW - HOUR))], NOW)).toEqual({ reviews: 0, new: 1 });
  });

  it('counts cards, not words: a word has a card each way', () => {
    expect(cardsDueToday([word(card(NOW - HOUR, [1]), card(NOW - HOUR))], NOW)).toEqual({ reviews: 1, new: 1 });
  });

  it('treats bookkeeping entries (too early, reset) as no answer', () => {
    expect(cardsDueToday([word(card(NOW - HOUR, [0.01, 3]))], NOW)).toEqual({ reviews: 0, new: 1 });
  });

  it('leaves out a known word never answered, whose cards the plugin turned off', () => {
    expect(cardsDueToday([known(card(NOW - HOUR), card(NOW - HOUR))], NOW)).toEqual({ reviews: 0, new: 0 });
  });

  it('keeps a known word that was answered, which RemNote still asks', () => {
    expect(cardsDueToday([known(card(NOW - HOUR, [1]), card(NOW - HOUR))], NOW)).toEqual({ reviews: 1, new: 1 });
  });

  it('does not count cards due tomorrow or never scheduled', () => {
    expect(cardsDueToday([word(card(NOW + 13 * HOUR, [1])), word(card(undefined, [1]))], NOW)).toEqual({ reviews: 0, new: 0 });
  });
});

it('spells out the breakdown', () => {
  expect(dueBreakdown({ reviews: 179, new: 766 })).toBe('179 reviews and 766 new cards');
  expect(dueBreakdown({ reviews: 1, new: 1 })).toBe('1 review and 1 new card');
});
