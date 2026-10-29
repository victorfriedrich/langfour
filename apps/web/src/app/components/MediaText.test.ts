import { expect, it } from 'vitest';
import { groupBlocks } from './MediaText';

it('puts consecutive list items in one list and runs cues together until a pause', () => {
  const groups = groupBlocks([
    { timestamp: null, text: 'Uno', block: 'li' },
    { timestamp: null, text: 'Dos', block: 'li' },
    { timestamp: null, text: 'Fin.' },
  ]);
  expect(groups.map((group) => [group.kind, group.chunks.length])).toEqual([['list', 2], ['block', 1]]);

  const cues = groupBlocks([
    { timestamp: [0, 1], text: 'Hola.' },
    { timestamp: [1.5, 2], text: '¿Qué tal?' },
    { timestamp: [5, 6], text: 'Adiós.' },
  ]);
  expect(cues.map((group) => group.chunks.map((chunk) => chunk.text))).toEqual([['Hola.', '¿Qué tal?'], ['Adiós.']]);
});
