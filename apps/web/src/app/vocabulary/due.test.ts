import { describe, expect, it } from 'vitest';
import type { CardLike, WordCards } from '../../../../remnote-plugin/src/stats';
import { wordsDueToday } from './due';

const NOW = new Date(2026, 9, 2, 12).getTime(); // noon, local time
const HOUR = 3_600_000;

const word = (...cards: CardLike[]): WordCards => ({ remId: 'r', wordId: 1, root: 'x', language: 'es', cards });
const card = (due: number | undefined, scores: number[] = []): CardLike => ({
  remId: 'r',
  nextRepetitionTime: due,
  repetitionHistory: scores.map((score, i) => ({ date: NOW - (i + 1) * 24 * HOUR, score })),
});

describe('wordsDueToday', () => {
  it('counts a reviewed card due today or overdue', () => {
    expect(wordsDueToday([word(card(NOW + 3 * HOUR, [1])), word(card(NOW - 48 * HOUR, [0]))], NOW)).toBe(2);
  });

  it('does not count a new card, even though RemNote gave it a due date', () => {
    expect(wordsDueToday([word(card(NOW - HOUR))], NOW)).toBe(0);
  });

  it('does not count bookkeeping entries (too early, reset) as reviews', () => {
    expect(wordsDueToday([word(card(NOW - HOUR, [0.01, 3]))], NOW)).toBe(0);
  });

  it('counts a word once when one of its cards is reviewed and due', () => {
    expect(wordsDueToday([word(card(NOW - HOUR), card(NOW - HOUR, [1]))], NOW)).toBe(1);
  });

  it('does not count cards due tomorrow or never scheduled', () => {
    expect(wordsDueToday([word(card(NOW + 13 * HOUR, [1])), word(card(undefined, [1]))], NOW)).toBe(0);
  });
});
