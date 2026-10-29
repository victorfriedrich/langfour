import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import ProgressOverview from './ProgressOverview';

const word = (root: string, addedAt: number | null) => ({ remId: root, wordId: 0, root, language: 'es', cards: [], addedAt });

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
