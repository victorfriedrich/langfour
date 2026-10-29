import { expect, it } from 'vitest';
import { createWordPopup } from './wordPopup';

const header = (wordText: string, root: string) =>
  createWordPopup(wordText, { id: 1, root, translation: 'x' }, null).querySelector('.popup-header')!.textContent;

it('shows the form tapped, then the dictionary form', () => {
  expect(header('charlan', 'charlar')).toBe('charlan (charlar)');
});

it('shows one form when they differ only in case', () => {
  expect(header('Perro', 'perro')).toBe('perro');
});
