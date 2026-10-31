import { fireEvent, render, screen, within } from '@testing-library/react';
import { expect, it } from 'vitest';
import type { CardLike } from '../../../../remnote-plugin/src/stats';
import ProgressOverview from './ProgressOverview';

const DAY_MS = 86_400_000;
const word = (root: string, cards: CardLike[] = [], translation: string | null = null) => ({
  remId: root,
  wordId: 0,
  root,
  language: 'es',
  translation,
  cards,
});
const saved = (root: string, addedAt: number) => ({ wordId: 0, root, language: 'es', addedAt });
/** A card answered "again" at each of these days ago, due again tomorrow. */
const forgotten = (...daysAgo: number[]): CardLike => ({
  remId: 'r',
  repetitionHistory: daysAgo.map((d) => ({ date: Date.now() - d * DAY_MS, score: 0 })),
  nextRepetitionTime: Date.now() + DAY_MS,
});

it('lists only the days of this week on which words were saved', () => {
  render(<ProgressOverview words={[word('el techo')]} saved={[saved('el techo', Date.now() - 1000), saved('el vino', Date.now() - 1000)]} />);
  const rows = screen.getAllByRole('listitem');
  expect(rows).toHaveLength(1);
  expect(rows[0]).toHaveTextContent('Today2el techo, el vino');
});

it('says so when no words were saved this week', () => {
  render(<ProgressOverview words={[word('el techo')]} saved={[saved('el vino', Date.now() - 8 * DAY_MS)]} />);
  expect(screen.queryByRole('listitem')).toBeNull();
  expect(screen.getByText('No words saved in the last seven days.')).toBeInTheDocument();
});

it('lists forgotten words, most often forgotten first, with meaning and when', () => {
  render(
    <ProgressOverview
      words={[word('la llave', [forgotten(9)], 'the key'), word('el techo', [forgotten(20, 3, 1)], 'the roof')]}
      saved={[]}
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
  const words = Array.from({ length: 7 }, (_, i) => word(`w${i}`, [forgotten(2)]));
  render(<ProgressOverview words={words} saved={[]} />);
  const section = screen.getByRole('heading', { name: /Forgotten recently/ }).closest('section')!;
  expect(within(section).getAllByRole('listitem')).toHaveLength(5);
  fireEvent.click(within(section).getByRole('button', { name: 'Show all 7' }));
  expect(within(section).getAllByRole('listitem')).toHaveLength(7);
});

it('lists learned words whose review is late, and how many dropped this week', () => {
  // Answered right 60 days ago with a 30-day gap: stopped counting 15 days ago.
  const late = (daysAgo: number): CardLike => ({
    remId: 'r',
    repetitionHistory: [{ date: Date.now() - daysAgo * DAY_MS, score: 1 }],
    nextRepetitionTime: Date.now() - (daysAgo - 30) * DAY_MS,
  });
  render(<ProgressOverview words={[word('la lámpara', [late(60)], 'the lamp'), word('el vino', [late(48)])]} saved={[]} />);
  const section = screen.getByRole('heading', { name: /Overdue/ }).closest('section')!;
  const rows = within(section).getAllByRole('listitem');
  expect(rows[0]).toHaveTextContent('el vino3 days ago');
  expect(rows[1]).toHaveTextContent('la lámparathe lamp');
  expect(within(section).getByText('1 this week')).toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: /Forgotten recently/ })).toBeNull();
});
