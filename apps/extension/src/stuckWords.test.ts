import { describe, expect, it } from 'vitest';
import type { BackendResponse } from './messages';
import { stuckWordsText, stuckWordsToShow, stuckWordsUrl } from './stuckWords';

const answer = (body: unknown, ok = true): BackendResponse => ({
  ok, status: ok ? 200 : 500, statusText: '', body: JSON.stringify(body),
});

describe('stuckWordsToShow', () => {
  it('counts the stuck words in the language', async () => {
    const asked: string[] = [];
    const count = await stuckWordsToShow('es', async () => false, async (path) => {
      asked.push(path);
      return answer({ words: [{}, {}, {}] });
    });
    expect(count).toBe(3);
    expect(asked).toEqual(['/api/vocabulary/stuck?language=es']);
  });

  it('shows nothing once the link was opened, without asking the API', async () => {
    let asked = false;
    const count = await stuckWordsToShow('es', async () => true, async () => {
      asked = true;
      return answer({ words: [{}] });
    });
    expect([count, asked]).toEqual([0, false]);
  });

  it('shows nothing when the API fails', async () => {
    expect(await stuckWordsToShow('es', async () => false, async () => answer({}, false))).toBe(0);
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
    expect(stuckWordsUrl('https://app.langfour.com')).toBe('https://app.langfour.com/vocabulary?words=stuck');
  });
});
