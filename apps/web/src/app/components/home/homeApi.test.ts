import { afterEach, expect, it } from 'vitest';
import {
  DEFAULT_FILTERS,
  formatDuration,
  homeQuery,
  peekAway,
  saveAway,
  shortTitle,
  takeAway,
  watchedText,
} from './homeApi';

afterEach(() => sessionStorage.clear());

it('asks for the filters it has', () => {
  expect(homeQuery('es', DEFAULT_FILTERS)).toBe('/api/home?language=es&topic=All&length=any');
  expect(homeQuery('es', { topic: 'Gaming', grammar: 'A2', length: 'long', q: ' gta ' })).toBe(
    '/api/home?language=es&topic=Gaming&length=long&grammar=A2&q=gta',
  );
});

it('writes lengths the way YouTube does', () => {
  expect(formatDuration(1348)).toBe('22:28');
  expect(formatDuration(200)).toBe('3:20');
  expect(formatDuration(3723)).toBe('1:02:03');
});

it('says how far into a video the learner got', () => {
  expect(watchedText(0.42, 1348)).toBe('watched 9 of 22 min');
  expect(watchedText(0.42, null)).toBe('watched 42%');
});

it('shortens a title for the pill', () => {
  expect(shortTitle('En este lugar no existe la noche: 24 horas de sol')).toBe('En este lugar no existe la noche');
  expect(shortTitle('Desayuno espacial')).toBe('Desayuno espacial');
  expect(shortTitle('a'.repeat(60))).toBe(`${'a'.repeat(39)}…`);
});

it('remembers the video left for until it is taken', () => {
  const away = { videoId: 'aaaaaaaaaaa', title: 'T', leftAt: '2026-11-03T12:00:00.000Z' };
  saveAway(away);
  expect(peekAway()).toEqual(away);
  expect(takeAway()).toEqual(away);
  expect(takeAway()).toBeNull();
});
