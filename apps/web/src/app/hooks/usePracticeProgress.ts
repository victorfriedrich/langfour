import { useContext, useEffect, useState } from 'react';
import { supabase } from '@/lib/supabaseclient';
import { UserContext } from '@/context/UserContext';
import type { ReviewProvider } from './useReviewProvider';
// The plugin's progress rules, shared so the Practice page and RemNote never
// disagree on what "learned" means.
import type { WordCards } from '../../../../remnote-plugin/src/stats';

const PAGE = 1000;
// srs_reviews.outcome and flashcardtests.test_result in RemNote's scores,
// which the stats module reads.
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

/** Words RemNote schedules, from what the plugin reported. */
async function remnoteWords(): Promise<WordCards[]> {
  type Row = {
    id: number;
    word_id: number;
    userwords: { words: { root: string; language: string } | null } | null;
    srs_cards: { next_due_at: string | null; srs_reviews: { reviewed_at: string; outcome: string }[] }[];
  };
  const rows = await selectAll<Row>(() =>
    supabase
      .from('srs_notes')
      .select('id, word_id, userwords!inner(words(root, language)), srs_cards(next_due_at, srs_reviews(reviewed_at, outcome))')
      .is('removed_at', null)
      .order('id'),
  );
  return rows.map((row) => ({
    remId: String(row.id),
    wordId: row.word_id,
    root: row.userwords?.words?.root ?? '',
    language: row.userwords?.words?.language ?? '?',
    cards: row.srs_cards.map((card) => ({
      remId: String(row.id),
      nextRepetitionTime: card.next_due_at ? Date.parse(card.next_due_at) : undefined,
      repetitionHistory: card.srs_reviews.map((r) => ({ date: Date.parse(r.reviewed_at), score: OUTCOME_SCORES[r.outcome] })),
    })),
  }));
}

/** Words Langfour schedules: one card per learning word, its history from
 *  flashcardtests (a right answer counts as "good", a wrong one as "again"). */
async function langfourWords(userId: string): Promise<WordCards[]> {
  type WordRow = { word_id: number; next_review_due_at: string | null; words: { root: string; language: string } | null };
  type TestRow = { word_id: number; test_result: boolean; tested_at: string };
  const [words, tests] = await Promise.all([
    selectAll<WordRow>(() =>
      supabase
        .from('userwords')
        .select('word_id, next_review_due_at, words(root, language)')
        .eq('user_id', userId)
        .eq('status', 'learning')
        .order('word_id'),
    ),
    selectAll<TestRow>(() =>
      supabase.from('flashcardtests').select('word_id, test_result, tested_at').eq('user_id', userId).order('id'),
    ),
  ]);
  const history = new Map<number, { date: number; score: number }[]>();
  for (const t of tests) {
    const list = history.get(t.word_id) ?? [];
    list.push({ date: Date.parse(t.tested_at), score: t.test_result ? 1 : 0 });
    history.set(t.word_id, list);
  }
  return words.map((w) => ({
    remId: String(w.word_id),
    wordId: w.word_id,
    root: w.words?.root ?? '',
    language: w.words?.language ?? '?',
    cards: [{
      remId: String(w.word_id),
      nextRepetitionTime: w.next_review_due_at ? Date.parse(w.next_review_due_at) : undefined,
      repetitionHistory: history.get(w.word_id) ?? [],
    }],
  }));
}

/** The words of whichever system schedules this user's reviews, in the
 *  shape the stats module reads. Null while loading. */
export const usePracticeProgress = (provider: ReviewProvider | null, refreshTrigger = 0) => {
  const { user } = useContext(UserContext);
  const [words, setWords] = useState<WordCards[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!provider || !user || user.is_anonymous) return;
    let cancelled = false;
    (provider === 'remnote' ? remnoteWords() : langfourWords(user.id))
      .then((result) => !cancelled && setWords(result))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : 'Could not load your progress'));
    return () => {
      cancelled = true;
    };
  }, [provider, user, refreshTrigger]);

  return { words, error };
};
