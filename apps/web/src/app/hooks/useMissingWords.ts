import { useState, useEffect, useContext } from 'react';
import { UserContext } from '@/context/UserContext';
// Must be the shared client. createBrowserClient (@supabase/ssr) keeps its
// session in document.cookie, but the session is written to localStorage by
// the supabase-js client in @/lib/supabaseclient — nothing in this app writes
// the auth cookie. A client built here would read `words` as `anon`, which
// works only while RLS is off and returns zero rows (with no error) once it
// is on.
import { supabase } from '@/lib/supabaseclient';

interface MissingWord {
  id: number;
  content: string;
  translation: string;
  /** Jev's ranking for this text, 1..5; null until the text is ranked. */
  importance: number | null;
  /** One of the text's most important words. */
  key: boolean;
}

interface ApiMissingWord {
  id: number;
  content: string;
  importance?: number | null;
  key?: boolean;
}

interface MissingWordsRequest {
  language_code: string;
}

// Videos come from the shared corpus; Library items are per user and have
// their own route.
export const useMissingWords = (videoId: string, source: 'videos' | 'media' = 'videos') => {
  const [recommendedWords, setRecommendedWords] = useState<MissingWord[]>([]);
  const [flaggedWords, setFlaggedWords] = useState<MissingWord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { fetchWithAuth, language } = useContext(UserContext);

  useEffect(() => {
    const fetchMissingWords = async () => {
      try {
        const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
        // Prepare the request body
        const requestBody: MissingWordsRequest = {
          language_code: language?.code || 'es' // Default to 'en' if language code is not available
        };

        const response = await fetchWithAuth(`${API_URL}/api/${source}/${encodeURIComponent(videoId)}/missing-words`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(requestBody),
        });

        if (!response.ok) {
          throw new Error('Failed to fetch missing words');
        }

        const data = await response.json();
        const missingWordsData: ApiMissingWord[] = data.missing_words;
        const byId = new Map(missingWordsData.map((word) => [word.id, word]));

        const { data: wordData, error: supabaseError } = await supabase
          .from('words')
          .select('id, root, translation, status')
          .in('id', missingWordsData.map((word) => word.id));

        if (supabaseError) {
          throw supabaseError;
        }

        const recommended: MissingWord[] = [];
        const flagged: MissingWord[] = [];

        wordData.forEach((word: { id: number; root: string; translation: string; status: string }) => {
          if (word.status === 'invalid') return;
          const missingWord = byId.get(word.id);
          const base = {
            id: word.id,
            content: missingWord?.content || '',
            translation: word.translation,
            importance: missingWord?.importance ?? null,
            key: missingWord?.key ?? false,
          };

          if (word.status === 'flagged') {
            flagged.push(base);
          } else {
            recommended.push(base);
          }
        });

        setRecommendedWords(recommended);
        setFlaggedWords(flagged);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred while fetching missing words');
      } finally {
        setIsLoading(false);
      }
    };

    fetchMissingWords();
  }, [videoId, source, fetchWithAuth, language]);

  return { recommendedWords, flaggedWords, isLoading, error };
};
