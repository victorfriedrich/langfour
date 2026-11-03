import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import type { StuckWord } from '../vocabulary/stuck';
import LearningWordsTable from './LearningWordsTable';

const { moveToKnown, none } = vi.hoisted(() => ({
  moveToKnown: vi.fn(async (ids: number[]) => ids),
  none: [] as never[], // one array: a new one each render would refetch forever
}));
let stuck: StuckWord[] | null = [];

vi.mock('@/lib/supabaseclient', () => ({ supabase: { rpc: vi.fn() } }));
vi.mock('../hooks/useGetSources', () => ({ useGetSources: () => ({ getSources: async () => [] }) }));
vi.mock('../hooks/useLearningWords', () => ({
  useGetLearningWords: () => ({ learningWords: none, isLoading: false, error: null }),
}));
vi.mock('../hooks/useOverdueWords', () => ({ useOverdueWords: () => ({ words: none }) }));
vi.mock('../hooks/useSetUserwordsStatus', () => ({ useSetUserwordsStatus: () => ({ updateUserwordsStatus: vi.fn() }) }));
vi.mock('../hooks/useStuckWords', () => ({ useStuckWords: () => ({ words: stuck, error: null, moveToKnown }) }));

const word = (word_id: number, word: string, videos = 0, lookups = 0): StuckWord => ({
  word_id, word, translation: null, videos, lookups, reason: 'common',
});

beforeEach(() => {
  moveToKnown.mockClear();
  window.history.replaceState(null, '', '/vocabulary');
});

it('has no tab when no common word is stuck', () => {
  stuck = [];
  render(<LearningWordsTable total={10} />);
  expect(screen.queryByText('Words you likely know')).toBeNull();
});

it('opens from its link with every word ticked except the looked-up ones', async () => {
  stuck = [word(1, 'que', 40), word(2, 'quedar', 41, 3), word(3, 'y')];
  window.history.replaceState(null, '', '/vocabulary?words=stuck');
  render(<LearningWordsTable total={10} />);

  expect(screen.getByText('3')).toBeTruthy(); // the tab's count
  expect(screen.getByText('in 41 videos, looked up 3×')).toBeTruthy();
  const boxes = screen.getAllByRole('checkbox') as HTMLInputElement[];
  expect(boxes.map((b) => b.checked)).toEqual([true, false, true]);

  fireEvent.click(screen.getByText('y')); // the row toggles too
  expect(screen.getByText('1 selected')).toBeTruthy();
  fireEvent.click(screen.getByText('Move to known'));
  expect(moveToKnown).toHaveBeenCalledWith([1]);
});
