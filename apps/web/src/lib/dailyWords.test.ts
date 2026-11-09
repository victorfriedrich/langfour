import { describe, expect, it } from 'vitest';
import { dailyWordsQuery, isDue, todayKey } from './dailyWords';

describe('daily words', () => {
  it('counts days in the learner’s own calendar', () => {
    expect(todayKey(new Date(2026, 10, 9, 23, 59))).toBe('2026-11-09');
    expect(todayKey(new Date(2026, 0, 2, 0, 1))).toBe('2026-01-02');
  });

  it('is due once a day, and only with a pace', () => {
    expect(isDue({ pace: 15, topics: [] }, '2026-11-09')).toBe(true);
    expect(isDue({ pace: 15, topics: [], last: '2026-11-08' }, '2026-11-09')).toBe(true);
    expect(isDue({ pace: 15, topics: [], last: '2026-11-09' }, '2026-11-09')).toBe(false);
    expect(isDue({ pace: 0, topics: [] }, '2026-11-09')).toBe(false);
    expect(isDue(undefined, '2026-11-09')).toBe(false);
  });

  it('asks for the pace and every topic', () => {
    expect(dailyWordsQuery('es', { pace: 15, topics: ['Cooking', 'Health & Fitness'] }))
      .toBe('/api/daily-words?language=es&n=15&topics=Cooking&topics=Health+%26+Fitness');
  });
});
