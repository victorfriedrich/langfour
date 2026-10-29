import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import Wordpanel from './Wordpanel';

const words = vi.hoisted(() => ({ recommendedWords: [] as { id: number; content: string; translation: string }[], flaggedWords: [], isLoading: false, error: null }));
vi.mock('../hooks/useMissingWords', () => ({ useMissingWords: () => words }));
vi.mock('../hooks/useUpdateUserwords', () => ({ useUpdateUserwords: () => ({ addWordsToUserwords: vi.fn() }) }));
vi.mock('../hooks/useSeenVideos', () => ({ useSeenVideos: () => ({ seenVideos: [], markVideoAsSeen: vi.fn() }) }));

beforeEach(() => { words.recommendedWords = []; });

it('says there is nothing new instead of an empty list when every word is known', () => {
  const onClose = vi.fn();
  render(<Wordpanel videoId="song" videoTitle="Canción de prueba" variant="page" source="media" onClose={onClose} />);
  expect(screen.getByText('Nothing new to learn here')).toBeInTheDocument();
  expect(screen.queryByText(/Recommended/)).not.toBeInTheDocument();
  expect(screen.queryByText('Select all')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /to learning set/ })).not.toBeInTheDocument();
  expect(screen.queryByText(/new words found/)).not.toBeInTheDocument();
  screen.getAllByRole('button', { name: 'Back to Media' })[1].click();
  expect(onClose).toHaveBeenCalledWith(0);
});

it('keeps the Seen button in the side panel when every word is known', () => {
  render(<Wordpanel videoId="video" videoTitle="Video" onClose={vi.fn()} />);
  expect(screen.getByText('Nothing new to learn here')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Seen/ })).toBeInTheDocument();
});

it('lists the words when there are some', () => {
  words.recommendedWords = [{ id: 1, content: 'luna', translation: 'moon' }];
  render(<Wordpanel videoId="song" videoTitle="Canción de prueba" variant="page" source="media" onClose={vi.fn()} />);
  expect(screen.getByText('Recommended')).toBeInTheDocument();
  expect(screen.getByText(/1 new word$/)).toBeInTheDocument();
  expect(screen.queryByText('Nothing new to learn here')).not.toBeInTheDocument();
  // Nothing to add until a word is picked, then the selection pill appears.
  expect(screen.queryByRole('button', { name: 'Add to learning set' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('luna'));
  expect(screen.getByText('1 selected')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Add to learning set' })).toBeInTheDocument();
});

it('shows the text beside the list, with its new words marked and pickable', () => {
  words.recommendedWords = [{ id: 1, content: 'luna', translation: 'moon' }];
  const transcript = [
    { timestamp: null, text: 'Canción', block: 'h2' as const, words: [[0, 7, 9]] as [number, number, number][] },
    { timestamp: null, text: 'La luna sale.', words: [[0, 2, 5], [3, 7, 1], [8, 12, 6]] as [number, number, number][] },
  ];
  render(<Wordpanel videoId="song" videoTitle="Canción de prueba" variant="page" source="media" transcript={transcript} onClose={vi.fn()} />);
  expect(screen.getByRole('heading', { name: 'Canción' })).toBeInTheDocument();
  // Only the new word is marked, and no sentence is repeated under the list.
  const marked = screen.getByRole('button', { name: 'luna', pressed: false });
  expect(screen.queryByRole('button', { name: 'sale' })).not.toBeInTheDocument();
  expect(screen.queryByText(/“/)).not.toBeInTheDocument();
  fireEvent.click(marked);
  expect(screen.getByText('1 selected')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'luna', pressed: true })).toBeInTheDocument();
  expect(screen.getByRole('checkbox')).toBeChecked();
});
