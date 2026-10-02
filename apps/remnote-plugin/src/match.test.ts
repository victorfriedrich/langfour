import { describe, expect, it } from 'vitest';
import { buildIndex, findExisting, forms, normalize, plainSides } from './match';

describe('normalize', () => {
  it.each([
    ['El Truco', 'truco'],
    ['la voz', 'voz'],
    ["l'acqua", 'acqua'],
    ['die Stimme', 'stimme'],
    ['coche (m.)', 'coche'],
    ['to speak', 'speak'],
    ['¡hola!', 'hola'],
    ['sin embargo', 'sin embargo'],
  ])('%s -> %s', (input, expected) => {
    expect(normalize(input)).toBe(expected);
  });

  it('keeps a lone article, which is a word in its own right', () => {
    expect(normalize('la')).toBe('la');
  });
});

it('splits list-like sides into parts', () => {
  expect(forms('el truco, la trampa')).toEqual(['truco la trampa', 'truco', 'trampa']);
  expect(forms('coche / carro')).toEqual(['coche carro', 'coche', 'carro']);
});

describe('plainSides', () => {
  it('reads text runs and ignores other elements', () => {
    expect(plainSides(['la ', { i: 'm', text: 'voz', b: true }, { i: 'q', _id: 'x' }])).toEqual(['la voz']);
  });

  it('splits at an inline card delimiter', () => {
    expect(plainSides(['hablar ', { i: 's' }, ' to speak'])).toEqual(['hablar ', ' to speak']);
  });

  it('handles missing text', () => {
    expect(plainSides(undefined)).toEqual([]);
  });
});

describe('findExisting', () => {
  const index = buildIndex([
    { remId: 'front', sides: ['la voz', 'voice'], reviews: 2 },
    { remId: 'back', sides: ['to speak', 'hablar'], reviews: 0 },
    { remId: 'list', sides: ['el truco, la trampa', 'trick'], reviews: 1 },
    { remId: 'sentence', sides: ['Mi coche es rojo', 'My car is red'], reviews: 9 },
  ]);

  it('matches either side, ignoring articles and case', () => {
    expect(findExisting(index, 'voz')?.remId).toBe('front');
    expect(findExisting(index, 'el voz')?.remId).toBe('front');
    expect(findExisting(index, 'hablar')?.remId).toBe('back');
  });

  it('matches one part of a list', () => {
    expect(findExisting(index, 'la trampa')?.remId).toBe('list');
  });

  it('does not match a word inside a sentence', () => {
    expect(findExisting(index, 'coche')).toBeUndefined();
  });

  it('prefers the card with more reviews', () => {
    const both = buildIndex([
      { remId: 'fresh', sides: ['perro'], reviews: 0 },
      { remId: 'studied', sides: ['el perro'], reviews: 5 },
    ]);
    expect(findExisting(both, 'perro')?.remId).toBe('studied');
  });
});
