import { useCallback, useContext } from 'react';
import { UserContext } from '@/context/UserContext';

export type WordBucket = 'probably' | 'should' | 'skip';

export interface BucketMove {
  word_id: number;
  was: WordBucket;
  now: WordBucket;
}

interface BucketWords {
  /** Words added half-way to known. */
  familiar: number[];
  /** Words added as ordinary learning words. */
  priority: number[];
  source: string;
  /** Words the learner moved out of the group Jev chose. */
  moves: BucketMove[];
}

export const useAddBucketWords = () => {
  const { fetchWithAuth } = useContext(UserContext);
  return useCallback(async (words: BucketWords) => {
    const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    const response = await fetchWithAuth(`${API_URL}/api/word-buckets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(words),
    });
    if (!response.ok) throw new Error('Failed to add words');
  }, [fetchWithAuth]);
};
