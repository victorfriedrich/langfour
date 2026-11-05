import { describe, expect, it } from 'vitest';
import type { BackendResponse } from './messages';
import { openedNow, stuckWordsText, stuckWordsToShow, stuckWordsUrl } from './stuckWords';

const answer = (body: unknown, ok = true): BackendResponse => ({
  ok, status: ok ? 200 : 500, statusText: '', body: JSON.stringify(body),
});

const LISTED = {
  words: [
    { word_id: 1, reason: 'common' },
    { word_id: 2, reason: 'common' },
    { word_id: 3, reason: 'seen' },
  ],
};

describe('stuckWordsToShow', () => {
  it('counts every listed word before the link was ever opened', async () => {
    const asked: string[] = [];
    const row = await stuckWordsToShow('es', async () => undefined, async (path) => {
      asked.push(path);
      return answer(LISTED);
    });
    expect(row).toEqual({ listed: [1, 2, 3], fresh: 3 });
    expect(asked).toEqual(['/api/vocabulary/stuck?language=es']);
  });

  it('counts only words listed since the link was last opened', async () => {
    const row = await stuckWordsToShow('es', async () => [1, 2], async () => answer(LISTED));
    expect(row.fresh).toBe(1);
  });

  it('counts nothing when every listed word was already shown', async () => {
    const row = await stuckWordsToShow('es', async () => [1, 2, 3, 9], async () => answer(LISTED));
    expect(row.fresh).toBe(0);
  });

  it('reads the old "opened" flag as the common words', async () => {
    const row = await stuckWordsToShow('es', async () => true, async () => answer(LISTED));
    expect(row.fresh).toBe(1);
  });

  it('shows nothing when the API fails', async () => {
    expect(await stuckWordsToShow('es', async () => undefined, async () => answer({}, false)))
      .toEqual({ listed: [], fresh: 0 });
  });
});

describe('openedNow', () => {
  it('remembers what was listed now and before', () => {
    expect(openedNow([1, 4], [1, 2])).toEqual([1, 4, 2]);
    expect(openedNow(true, [3])).toEqual([3]);
  });
});

describe('stuckWordsText', () => {
  it('reads as one line', () => {
    expect(stuckWordsText(45)).toBe('45 words you likely know are still marked learning');
    expect(stuckWordsText(1)).toBe('1 word you likely know is still marked learning');
  });
});

describe('stuckWordsUrl', () => {
  it('opens the Vocabulary tab', () => {
    expect(stuckWordsUrl('https://app.langfour.com')).toBe('https://app.langfour.com/practice?words=stuck');
  });
});
