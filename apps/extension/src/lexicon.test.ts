import { describe, expect, it } from 'vitest';
import { classifyTokens, parseLexicon } from './lexicon';
import type { WordStatus } from './messages';

// id, root, forms: lines as lexicon_page returns them.
const lexicon = parseLexicon([
  ['1\tcomo', '2\tcomer\tcomo\tcomí', '3\tla casa\tcasa\tcasas'].join('\n'),
  ['4\tHaus\tHäuser', '5\tcasar\tcasas'].join('\n'),
]);

const classify = (tokens: string[], statuses: [number, WordStatus][] = []) =>
  Object.fromEntries(classifyTokens(tokens, lexicon, new Map(statuses)).map((w) => [w.token, [w.word_id, w.status]]));

describe('classifyTokens', () => {
  it('matches roots and word forms, and leaves out what is not vocabulary', () => {
    expect(classify(['comí', 'casas', 'Trump'])).toEqual({ comí: [2, 'new'], casas: [3, 'new'] });
  });

  it('tries a token as written, then lowercased', () => {
    expect(classify(['Comí', 'Haus', 'Häuser', 'HAUS'])).toEqual({ Comí: [2, 'new'], Haus: [4, 'new'], Häuser: [4, 'new'] });
  });

  it('prefers the root over a word form, then the lower id', () => {
    // "como" is the root of 1 and a form of 2; "casas" a form of 3 and 5.
    expect(classify(['como', 'casas'])).toEqual({ como: [1, 'new'], casas: [3, 'new'] });
  });

  it('lets the user\'s best relation win: a spelling is only new if none of its words is known', () => {
    expect(classify(['como'], [[2, 'known']])).toEqual({ como: [2, 'known'] });
    expect(classify(['casas'], [[3, 'learning'], [5, 'ignored']])).toEqual({ casas: [5, 'ignored'] });
    expect(classify(['casas'], [[5, 'learning']])).toEqual({ casas: [5, 'learning'] });
  });

  it('answers each distinct token once and skips empty and over-long ones', () => {
    const words = classifyTokens(['casas', 'casas', '', 'x'.repeat(65)], lexicon, new Map());
    expect(words).toEqual([{ token: 'casas', word_id: 3, status: 'new' }]);
  });
});
