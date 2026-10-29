import { fireEvent, render, screen, within } from '@testing-library/react';
import { expect, it } from 'vitest';
import type { CardLike } from '../../../../remnote-plugin/src/stats';
import ProgressOverview from './ProgressOverview';

const DAY_MS = 86_400_000;
const word = (root: string, addedAt: number | null, cards: CardLike[] = [], translation: string | null = null) => ({
  remId: root,
  wordId: 0,
  root,
  language: 'es',
  translation,
  cards,
  addedAt,
});
/** A card answered "again" at each of these days ago, due again tomorrow. */
const forgotten = (...daysAgo: number[]): CardLike => ({
  remId: 'r',
  repetitionHistory: daysAgo.map((d) => ({ date: Date.now() - d * DAY_MS, score: 0 })),
  nextRepetitionTime: Date.now() + DAY_MS,
});

it('lists only the days of this week on which words were saved', () => {
  render(<ProgressOverview words={[word('el techo', Date.now() - 1000), word('el vino', Date.now() - 1000)]} />);
  const rows = screen.getAllByRole('listitem');
  expect(rows).toHaveLength(1);
  expect(rows[0]).toHaveTextContent('Today2el techo, el vino');
});

it('says so when no words were saved this week', () => {
  render(<ProgressOverview words={[word('el techo', null)]} />);
  expect(screen.queryByRole('listitem')).toBeNull();
  expect(screen.getByText('No words saved in the last seven days.')).toBeInTheDocument();
});

it('lists forgotten words, most often forgotten first, with meaning and when', () => {
  render(
    <ProgressOverview
      words={[word('la llave', null, [forgotten(9)], 'the key'), word('el techo', null, [forgotten(20, 3, 1)], 'the roof')]}
    />,
  );
  const section = screen.getByRole('heading', { name: /Forgotten recently/ }).closest('section')!;
  const rows = within(section).getAllByRole('listitem');
  expect(rows[0]).toHaveTextContent('el techothe roof');
  expect(rows[0]).toHaveTextContent('Forgotten 3 times');
  expect(rows[0]).toHaveTextContent('Yesterday');
  expect(rows[1]).toHaveTextContent('Forgotten once');
});

it('shows five forgotten words until asked for all', () => {
  const words = Array.from({ length: 7 }, (_, i) => word(`w${i}`, null, [forgotten(2)]));
  render(<ProgressOverview words={words} />);
  const section = screen.getByRole('heading', { name: /Forgotten recently/ }).closest('section')!;
  expect(within(section).getAllByRole('listitem')).toHaveLength(5);
  fireEvent.click(within(section).getByRole('button', { name: 'Show all 7' }));
  expect(within(section).getAllByRole('listitem')).toHaveLength(7);
});
