import { useCallback, useContext, useEffect, useState } from 'react';
import { UserContext } from '@/context/UserContext';
import type { StuckWord } from '../vocabulary/stuck';

/**
 * Common words still in learning that were never reviewed, in the sidebar's
 * language (apps/api/vocabulary_routes.py). Moving them to known goes through
 * the API, the same path as the MCP's set_word_status.
 */
export const useStuckWords = () => {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  const { fetchWithAuth, user, language } = useContext(UserContext);
  const code = language?.code;
  const [words, setWords] = useState<StuckWord[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user || user.is_anonymous || !code) return;
    let cancelled = false;
    (async () => {
      try {
        const response = await fetchWithAuth(`${API_URL}/api/vocabulary/stuck?language=${code}`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        if (!cancelled) setWords(data.words);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load the words');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [API_URL, fetchWithAuth, user, code]);

  const moveToKnown = useCallback(
    async (wordIds: number[]) => {
      const response = await fetchWithAuth(`${API_URL}/api/vocabulary/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ word_ids: wordIds, status: 'known' }),
      });
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      const { moved } = (await response.json()) as { moved: number[] };
      setWords((prev) => prev && prev.filter((w) => !moved.includes(w.word_id)));
      return moved;
    },
    [API_URL, fetchWithAuth],
  );

  return { words, error, moveToKnown };
};
