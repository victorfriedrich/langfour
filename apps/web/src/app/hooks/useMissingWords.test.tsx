import React from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { UserContext } from '@/context/UserContext';
import { RANKING_POLL_MS, useMissingWords } from './useMissingWords';

vi.mock('@/lib/supabaseclient', () => ({
  supabase: {
    from: () => ({
      select: () => ({
        in: async (_: string, ids: number[]) => ({
          data: ids.map((id) => ({ id, root: `w${id}`, translation: `t${id}`, status: 'learning' })),
          error: null,
        }),
      }),
    }),
  },
}));

afterEach(() => {
  vi.useRealTimers();
});

const answer = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

function render(fetchWithAuth: (url: string) => Promise<Response>) {
  const value = { fetchWithAuth, language: { code: 'es' } } as unknown as React.ContextType<typeof UserContext>;
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <UserContext.Provider value={value}>{children}</UserContext.Provider>
  );
  return renderHook(() => useMissingWords('vid1'), { wrapper });
}

it('shows the unranked list at once and swaps in the key words once they are ranked', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const fetchWithAuth = vi.fn()
    .mockResolvedValueOnce(answer({ missing_words: [{ id: 1, content: 'a' }, { id: 2, content: 'b' }], ranking: true }))
    .mockResolvedValueOnce(answer({
      missing_words: [{ id: 1, content: 'a', importance: 2, key: false }, { id: 2, content: 'b', importance: 4.5, key: true }],
      ranking: false,
    }));
  const { result, unmount } = render(fetchWithAuth);

  await waitFor(() => expect(result.current.isLoading).toBe(false));
  expect(result.current.recommendedWords.map((w) => w.key)).toEqual([false, false]);

  await act(async () => { await vi.advanceTimersByTimeAsync(RANKING_POLL_MS); });
  await waitFor(() => expect(result.current.recommendedWords.find((w) => w.id === 2)?.key).toBe(true));
  expect(fetchWithAuth).toHaveBeenCalledTimes(2);

  await act(async () => { await vi.advanceTimersByTimeAsync(RANKING_POLL_MS * 3); });
  expect(fetchWithAuth).toHaveBeenCalledTimes(2);
  unmount();
});

it('stops asking when the panel closes', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const fetchWithAuth = vi.fn(async () => answer({ missing_words: [{ id: 1, content: 'a' }], ranking: true }));
  const { result, unmount } = render(fetchWithAuth);
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  unmount();
  await act(async () => { await vi.advanceTimersByTimeAsync(RANKING_POLL_MS * 5); });
  expect(fetchWithAuth).toHaveBeenCalledTimes(1);
});
