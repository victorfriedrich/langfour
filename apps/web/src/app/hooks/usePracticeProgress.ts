import { useContext, useEffect, useState } from 'react';
import { supabase } from '@/lib/supabaseclient';
import { UserContext } from '@/context/UserContext';
import type { ReviewProvider } from './useReviewProvider';
// The plugin's progress rules, shared so the Practice page and RemNote never
// disagree on what "learned" means.
import type { WordCards } from '../../../../remnote-plugin/src/stats';

/** A word with its cards and its translation. */
export type ProgressWord = WordCards & { translation: string | null };

/** A word the user saved, and when. */
export type SavedWord = { wordId: number; root: string; language: string; addedAt: number };

const PAGE = 1000;
const DAY_MS = 86_400_000;
// srs_reviews.outcome in RemNote's scores, which the stats module reads.
const OUTCOME_SCORES: Record<string, number> = { again: 0, hard: 0.5, good: 1, easy: 1.5 };

type Query = { range: (from: number, to: number) => PromiseLike<{ data: unknown[] | null; error: unknown }> };

async function selectAll<T>(build: () => Query): Promise<T[]> {
  const rows: T[] = [];
  for (let from = 0; ; from += PAGE) {
    const { data, error } = await build().range(from, from + PAGE - 1);
    if (error) throw error;
    rows.push(...((data ?? []) as T[]));
    if (!data || data.length < PAGE) return rows;
  }
}

/** userwords.created_at is a timestamp without a zone that holds UTC; read
 *  bare, the browser would take it as local time. */
const utcMs = (timestamp: string) => Date.parse(/(Z|[+-]\d\d:?\d\d)$/i.test(timestamp) ? timestamp : `${timestamp}Z`);

/** The user's words in one scheduler, with their cards and reviews: Langfour's
 *  own (one card per learning word) or RemNote's, as the plugin reported them. */
async function providerWords(provider: ReviewProvider): Promise<ProgressWord[]> {
  type Row = {
    id: number;
    word_id: number;
    userwords: { words: { root: string; language: string; translation: string | null } | null } | null;
    srs_cards: { next_due_at: string | null; srs_reviews: { reviewed_at: string; outcome: string }[] }[];
  };
  const rows = await selectAll<Row>(() => {
    const query = supabase
      .from('srs_notes')
      .select('id, word_id, userwords!inner(words(root, language, translation)), srs_cards(next_due_at, srs_reviews(reviewed_at, outcome))')
      .eq('provider', provider)
      .is('removed_at', null);
    // Langfour keeps cards for known words that have review history; its
    // progress is about the words still being learned. RemNote shows every
    // word with a Rem except those whose cards are turned off.
    return (provider === 'langfour' ? query.eq('userwords.status', 'learning') : query.neq('userwords.status', 'disabled'))
      .order('id');
  });
  return rows.map((row) => ({
    remId: String(row.id),
    wordId: row.word_id,
    root: row.userwords?.words?.root ?? '',
    language: row.userwords?.words?.language ?? '?',
    translation: row.userwords?.words?.translation ?? null,
    cards: row.srs_cards.map((card) => ({
      remId: String(row.id),
      nextRepetitionTime: card.next_due_at ? Date.parse(card.next_due_at) : undefined,
      repetitionHistory: card.srs_reviews.map((r) => ({ date: Date.parse(r.reviewed_at), score: OUTCOME_SCORES[r.outcome] })),
    })),
  }));
}

/** The words saved to learn in the last eight days, read from userwords so
 *  they show as soon as they're saved, before RemNote has synced them. Words
 *  marked known aren't new words to learn. */
async function savedWords(userId: string): Promise<SavedWord[]> {
  type Row = { word_id: number; created_at: string; words: { root: string; language: string } | null };
  // A day's margin past the week; the overview cuts it at local midnight.
  const since = new Date(Date.now() - 8 * DAY_MS).toISOString();
  const rows = await selectAll<Row>(() =>
    supabase
      .from('userwords')
      .select('word_id, created_at, words!inner(root, language)')
      .eq('user_id', userId)
      .eq('status', 'learning')
      .gte('created_at', since)
      .order('id'),
  );
  return rows.map((row) => ({
    wordId: row.word_id,
    root: row.words?.root ?? '',
    language: row.words?.language ?? '?',
    addedAt: utcMs(row.created_at),
  }));
}

/** The words of whichever system schedules this user's reviews, in the
 *  shape the stats module reads, and the words saved this week. Null while
 *  loading. */
export const usePracticeProgress = (provider: ReviewProvider | null, refreshTrigger = 0) => {
  const { user } = useContext(UserContext);
  const [progress, setProgress] = useState<{ words: ProgressWord[]; saved: SavedWord[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!provider || !user || user.is_anonymous) return;
    let cancelled = false;
    Promise.all([providerWords(provider), savedWords(user.id)])
      .then(([words, saved]) => !cancelled && setProgress({ words, saved }))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : 'Could not load your progress'));
    return () => {
      cancelled = true;
    };
  }, [provider, user, refreshTrigger]);

  return { words: progress?.words ?? null, saved: progress?.saved ?? null, error };
};
