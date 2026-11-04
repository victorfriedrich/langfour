import { useState, useEffect, useContext } from 'react';
import { UserContext } from '@/context/UserContext';
// Must be the shared client. createBrowserClient (@supabase/ssr) keeps its
// session in document.cookie, but the session is written to localStorage by
// the supabase-js client in @/lib/supabaseclient — nothing in this app writes
// the auth cookie. A client built here would read `words` as `anon`, which
// works only while RLS is off and returns zero rows (with no error) once it
// is on.
import { supabase } from '@/lib/supabaseclient';
import type { WordBucket } from './useAddBucketWords';

interface MissingWord {
  id: number;
  content: string;
  translation: string;
  /** Jev's ranking for this text, 1..5; null until the text is ranked. */
  importance: number | null;
  /** One of the text's most important words. */
  key: boolean;
  /** Where the word starts, for accounts with the three groups. */
  bucket?: WordBucket;
  /** Jev's rating of whether the learner can work it out, 1..5. */
  familiarity?: number | null;
}

interface ApiMissingWord {
  id: number;
  content: string;
  importance?: number | null;
  key?: boolean;
  bucket?: WordBucket;
  familiarity?: number | null;
}

interface MissingWordsRequest {
  language_code: string;
}

// The API answers before Jev has ranked a text it hasn't seen, with
// `ranking: true`, and saves the ranks when they come (2-5 s). Until then the
// list shows unranked and is asked for again, so the key words move to the
// top once they exist. A failed ranking is started again by the next ask, so
// the cap also bounds how often Jev is retried while the panel is open.
export const RANKING_POLL_MS = 2000;
const RANKING_POLLS = 10;

// Videos come from the shared corpus; Library items are per user and have
// their own route.
export const useMissingWords = (videoId: string, source: 'videos' | 'media' = 'videos') => {
  const [recommendedWords, setRecommendedWords] = useState<MissingWord[]>([]);
  const [flaggedWords, setFlaggedWords] = useState<MissingWord[]>([]);
  const [buckets, setBuckets] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { fetchWithAuth, language } = useContext(UserContext);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const fetchMissingWords = async (poll = 0) => {
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
        if (cancelled) return;
        const missingWordsData: ApiMissingWord[] = data.missing_words;
        const byId = new Map(missingWordsData.map((word) => [word.id, word]));

        const { data: wordData, error: supabaseError } = await supabase
          .from('words')
          .select('id, root, translation, status')
          .in('id', missingWordsData.map((word) => word.id));

        if (supabaseError) {
          throw supabaseError;
        }
        if (cancelled) return;

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
            bucket: missingWord?.bucket,
            familiarity: missingWord?.familiarity ?? null,
          };

          if (word.status === 'flagged') {
            flagged.push(base);
          } else {
            recommended.push(base);
          }
        });

        setRecommendedWords(recommended);
        setFlaggedWords(flagged);
        setBuckets(Boolean(data.buckets));
        if (data.ranking && poll < RANKING_POLLS) {
          timer = setTimeout(() => fetchMissingWords(poll + 1), RANKING_POLL_MS);
        }
      } catch (err) {
        // A failed poll leaves the unranked list up rather than replacing it.
        if (!cancelled && poll === 0) {
          setError(err instanceof Error ? err.message : 'An error occurred while fetching missing words');
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    fetchMissingWords();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [videoId, source, fetchWithAuth, language]);

  return { recommendedWords, flaggedWords, buckets, isLoading, error };
};
