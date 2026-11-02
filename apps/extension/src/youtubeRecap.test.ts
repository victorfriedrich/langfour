import { describe, expect, it } from 'vitest';
import { addLabel, picks, recapPath, recapStats, yesterday } from './youtubeRecap';

describe('yesterday', () => {
  it('is the local day before, as a date and its bounds', () => {
    const now = new Date(2026, 10, 2, 9, 30); // 2 Nov, 09:30 local
    const { day, start, end } = yesterday(now);
    expect(day).toBe('2026-11-01');
    expect(new Date(start).getTime()).toBe(new Date(2026, 10, 1).getTime());
    expect(new Date(end).getTime()).toBe(new Date(2026, 10, 2).getTime());
    expect(recapPath('es', now)).toContain('/api/watch/recap?language=es&day=2026-11-01&start=');
  });
});

describe('recap text', () => {
  it('says how much was watched', () => {
    expect(recapStats({ videos: 3, minutes: 41 })).toBe('3 videos · 41 min');
    expect(recapStats({ videos: 1, minutes: 0 })).toBe('1 video');
    expect(addLabel(4)).toBe('Add 4 to reviews');
  });

  it('adds the words not tapped away', () => {
    const recap = { day: '2026-11-01', videos: 2, minutes: 9, words: [
      { word_id: 1, word: 'el alquiler', video_id: 'a' },
      { word_id: 2, word: 'el casero', video_id: 'b' },
    ] };
    expect(picks(recap, new Set([2]))).toEqual([{ word_id: 1, video_id: 'a' }]);
  });
});
