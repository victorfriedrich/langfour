// hooks/useWordDetails.ts
import { useState, useEffect } from 'react';
import { supabase } from '@/lib/supabaseclient';

interface Word {
  word_id: number;
  word: string;
  translation: string;
  status: 'unverified' | 'valid' | 'flagged' | 'invalid';
}

export const useWordDetails = (wordIds: number[]) => {
  const [words, setWords] = useState<Word[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Callers pass a fresh array on every render; depend on its contents, or
  // the effect re-runs, resets state and renders again without end.
  const key = wordIds.join(',');

  useEffect(() => {
    const ids = key ? key.split(',').map(Number) : [];
    if (!ids.length) {
      setWords((prev) => (prev.length ? [] : prev));
      return;
    }

    const fetchWordDetails = async () => {
      setLoading(true);
      try {
        const { data, error } = await supabase
          .rpc('get_words_by_ids', {
            word_ids: ids
          });

        if (error) throw error;

        const { data: validityData, error: validityError } = await supabase
          .from('words')
          .select('id, status')
          .in('id', ids);

        if (validityError) throw validityError;

        const statusByWordId = new Map<number, Word['status']>(
          (validityData || []).map((word: { id: number; status: Word['status'] }) => [word.id, word.status])
        );

        setWords(
          (data || []).map((word: { word_id: number; word: string; translation: string }) => ({
            ...word,
            status: statusByWordId.get(word.word_id) ?? 'unverified',
          }))
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch word details');
      } finally {
        setLoading(false);
      }
    };

    fetchWordDetails();
  }, [key]);

  return { words, loading, error };
};
