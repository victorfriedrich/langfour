import { describe, expect, it } from 'vitest';
import { practiceVerdict } from './practice';

const NOW = 1_780_000_000_000;
const DAY = 86_400_000;

describe('practiceVerdict', () => {
  it('always applies a wrong answer, due or not', () => {
    expect(practiceVerdict({ outcome: 'again' }, { nextRepetitionTime: NOW + 30 * DAY }, NOW)).toBe('apply');
  });

  it('applies a right answer only to a due card', () => {
    expect(practiceVerdict({ outcome: 'good' }, { nextRepetitionTime: NOW - DAY }, NOW)).toBe('apply');
    expect(practiceVerdict({ outcome: 'good' }, { nextRepetitionTime: NOW + DAY }, NOW)).toBe('not_due');
  });

  it('treats an unscheduled card as due', () => {
    expect(practiceVerdict({ outcome: 'good' }, {}, NOW)).toBe('apply');
  });

  it('skips a card RemNote no longer has', () => {
    expect(practiceVerdict({ outcome: 'again' }, undefined, NOW)).toBe('card_missing');
  });
});
