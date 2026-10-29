import { describe, expect, it } from 'vitest';
import { practiceVerdict, reviewAddedSince } from './practice';

const NOW = 1_780_000_000_000;
const DAY = 86_400_000;

describe('practiceVerdict', () => {
  it('always applies a wrong answer, due or not', () => {
    expect(practiceVerdict({ outcome: 'again' }, { nextRepetitionTime: NOW + 30 * DAY }, true, NOW)).toBe('apply');
  });

  it('applies a right answer only to a due card', () => {
    expect(practiceVerdict({ outcome: 'good' }, { nextRepetitionTime: NOW - DAY }, true, NOW)).toBe('apply');
    expect(practiceVerdict({ outcome: 'good' }, { nextRepetitionTime: NOW + DAY }, true, NOW)).toBe('not_due');
  });

  it('treats an unscheduled card as due', () => {
    expect(practiceVerdict({ outcome: 'good' }, {}, true, NOW)).toBe('apply');
  });

  it('skips a card RemNote no longer has', () => {
    expect(practiceVerdict({ outcome: 'again' }, undefined, true, NOW)).toBe('card_missing');
  });

  it('never touches a card whose flashcards are turned off', () => {
    expect(practiceVerdict({ outcome: 'again' }, { nextRepetitionTime: NOW - DAY }, false, NOW)).toBe('practice_off');
  });
});

describe('reviewAddedSince', () => {
  it('finds the review an interrupted attempt added', () => {
    expect(reviewAddedSince(2, [{ date: 1 }, { date: 2 }, { date: 3 }])).toBe(3);
  });

  it('reports none when the attempt stopped before changing the card', () => {
    expect(reviewAddedSince(2, [{ date: 1 }, { date: 2 }])).toBeUndefined();
  });
});
