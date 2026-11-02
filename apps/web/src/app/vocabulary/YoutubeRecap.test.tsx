import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import YoutubeRecap from './YoutubeRecap';

const recap = {
  day: '2026-11-01', videos: 3, minutes: 41, words: [
    { word_id: 1, word: 'el alquiler', video_id: 'aaaaaaaaaaa' },
    { word_id: 2, word: 'la fianza', video_id: 'aaaaaaaaaaa' },
    { word_id: 3, word: 'el casero', video_id: 'bbbbbbbbbbb' },
  ],
};

it('shows what was watched and the words in one row', () => {
  render(<YoutubeRecap recap={recap} onAdd={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByRole('heading').textContent).toBe('Yesterday on YouTube 3 videos · 41 min');
  expect(screen.getByText('el alquiler').closest('p')?.textContent).toBe('el alquiler, la fianza, el casero');
  expect(screen.getByRole('button', { name: 'Add 3 to reviews' })).toBeTruthy();
});

it('adds all but the words tapped away, and says how many the API added', async () => {
  // el casero was saved meanwhile elsewhere, so only one is new.
  const onAdd = vi.fn().mockResolvedValue(['el alquiler']);
  render(<YoutubeRecap recap={recap} onAdd={onAdd} onClose={vi.fn()} />);
  fireEvent.click(screen.getByText('la fianza'));
  expect(screen.getByText('la fianza').className).toContain('text-gray-400');
  fireEvent.click(screen.getByRole('button', { name: 'Add 2 to reviews' }));
  expect(onAdd).toHaveBeenCalledWith([
    { word_id: 1, video_id: 'aaaaaaaaaaa' },
    { word_id: 3, video_id: 'bbbbbbbbbbb' },
  ]);
  await waitFor(() => expect(screen.getByText('Added 1 to reviews')).toBeTruthy());
});

it('puts it away with Not now', () => {
  const onClose = vi.fn();
  render(<YoutubeRecap recap={recap} onAdd={vi.fn()} onClose={onClose} />);
  fireEvent.click(screen.getByRole('button', { name: 'Not now' }));
  expect(onClose).toHaveBeenCalled();
});
