import { useContext, useEffect, useState } from 'react';
import { supabase } from '@/lib/supabaseclient';
import { UserContext } from '@/context/UserContext';
import type { ReviewProvider } from './useReviewProvider';
// The plugin's progress rules, shared so the Practice page and RemNote never
// disagree on what "learned" means.
import type { WordCards } from '../../../../remnote-plugin/src/stats';

/** A word with its cards, and when the user saved it. */
export type ProgressWord = WordCards & { addedAt: number | null };

const PAGE = 1000;
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

/** The user's words in one scheduler, with their cards and reviews: Langfour's
 *  own (one card per learning word) or RemNote's, as the plugin reported them. */
async function providerWords(provider: ReviewProvider): Promise<ProgressWord[]> {
  type Row = {
    id: number;
    word_id: number;
    userwords: { created_at: string | null; words: { root: string; language: string } | null } | null;
    srs_cards: { next_due_at: string | null; srs_reviews: { reviewed_at: string; outcome: string }[] }[];
  };
  const rows = await selectAll<Row>(() => {
    const query = supabase
      .from('srs_notes')
      .select('id, word_id, userwords!inner(created_at, words(root, language)), srs_cards(next_due_at, srs_reviews(reviewed_at, outcome))')
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
    addedAt: row.userwords?.created_at ? Date.parse(row.userwords.created_at) : null,
    cards: row.srs_cards.map((card) => ({
      remId: String(row.id),
      nextRepetitionTime: card.next_due_at ? Date.parse(card.next_due_at) : undefined,
      repetitionHistory: card.srs_reviews.map((r) => ({ date: Date.parse(r.reviewed_at), score: OUTCOME_SCORES[r.outcome] })),
    })),
  }));
}

/** The words of whichever system schedules this user's reviews, in the
 *  shape the stats module reads. Null while loading. */
export const usePracticeProgress = (provider: ReviewProvider | null, refreshTrigger = 0) => {
  const { user } = useContext(UserContext);
  const [words, setWords] = useState<ProgressWord[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!provider || !user || user.is_anonymous) return;
    let cancelled = false;
    providerWords(provider)
      .then((result) => !cancelled && setWords(result))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : 'Could not load your progress'));
    return () => {
      cancelled = true;
    };
  }, [provider, user, refreshTrigger]);

  return { words, error };
};
