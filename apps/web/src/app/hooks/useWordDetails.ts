// hooks/useWordDetails.ts
import { useState, useEffect } from 'react';
import { supabase } from '@/lib/supabaseclient';

interface Word {
  word_id: number;
  word: string;
  translation: string;
  cognate: string | null;
}

export const useWordDetails = (wordIds: number[]) => {
  const [words, setWords] = useState<Word[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!wordIds.length) {
      setWords([]);
      return;
    }

    const fetchWordDetails = async () => {
      setLoading(true);
      try {
        const { data, error } = await supabase
          .rpc('get_words_by_ids', {
            word_ids: wordIds
          });

        if (error) throw error;

        const { data: validityData, error: validityError } = await supabase
          .from('words')
          .select('id, cognate')
          .in('id', wordIds);

        if (validityError) throw validityError;

        const cognateByWordId = new Map<number, string | null>(
          (validityData || []).map((word: { id: number; cognate: string | null }) => [word.id, word.cognate])
        );

        setWords(
          (data || []).map((word: { word_id: number; word: string; translation: string }) => ({
            ...word,
            cognate: cognateByWordId.get(word.word_id) ?? null,
          }))
        );
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch word details');
      } finally {
        setLoading(false);
      }
    };

    fetchWordDetails();
  }, [wordIds]);

  return { words, loading, error };
};
