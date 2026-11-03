import { describe, expect, it } from 'vitest';
import { evidence, preselected, type StuckWord } from './stuck';

const word = (word_id: number, videos = 0, lookups = 0): StuckWord => ({
  word_id, word: `w${word_id}`, translation: null, videos, lookups, reason: 'common',
});

describe('preselected', () => {
  it('ticks every word except the ones looked up', () => {
    expect(preselected([word(1, 40), word(2, 41, 3), word(3)])).toEqual([1, 3]);
  });
});

describe('evidence', () => {
  it('names videos and look-ups', () => {
    expect(evidence(word(1, 1240, 3))).toBe('in 1,240 videos, looked up 3×');
    expect(evidence(word(1, 1))).toBe('in 1 video');
  });

  it('is empty without either', () => {
    expect(evidence(word(1))).toBe('');
  });
});
