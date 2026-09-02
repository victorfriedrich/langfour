import { supabase } from '@/lib/supabaseclient';

export const useUpdateUserwords = () => {
  /**
   * Move a set of words into the user's word list,
   * with an optional status and a required source tag.
   *
   * @param wordIds  Array of word IDs to upsert
   * @param source   Identifier for where these words came from
   * @param status   "learning" (default) or "known"
   */
  const addWordsToUserwords = async (
    wordIds: number[],
    source: string,
    status: 'learning' | 'known' = 'learning'
  ) => {
    try {
      const uniqueWordIds = Array.from(new Set(wordIds));
      let wordIdsToAdd = uniqueWordIds;

      // Importing a deck into practice must never downgrade an existing known
      // word back to learning. The move RPC is an upsert, so remove known words
      // before calling it rather than relying on its conflict behaviour.
      if (status === 'learning' && uniqueWordIds.length > 0) {
        // NOTE: this query MUST be scoped to the current user. Without the
        // user_id filter it reads every user's rows, so a word any other user
        // has marked 'known' is silently dropped from this import and never
        // added. RLS would scope it implicitly, but the filter is stated
        // explicitly here so the behaviour does not depend on RLS being on.
        const { data: authData } = await supabase.auth.getUser();
        const currentUserId = authData?.user?.id;
        if (!currentUserId) {
          throw new Error('Not signed in');
        }

        const { data: knownWords, error: knownWordsError } = await supabase
          .from('userwords')
          .select('word_id')
          .eq('user_id', currentUserId)
          .eq('status', 'known')
          .in('word_id', uniqueWordIds);

        if (knownWordsError) {
          console.error('Error checking known words:', knownWordsError);
          throw knownWordsError;
        }

        const knownWordIds = new Set(
          (knownWords ?? []).map(({ word_id }) => Number(word_id))
        );
        wordIdsToAdd = uniqueWordIds.filter((wordId) => !knownWordIds.has(wordId));
      }

      if (wordIdsToAdd.length === 0) {
        return [];
      }

      const { data, error } = await supabase.rpc(
        'move_words_to_userwords',
        {
          _word_ids: wordIdsToAdd,
          _status: status,
          _source: source,
        }
      );

      if (error) {
        console.error('Supabase RPC error:', error);
        throw error;
      }

      console.log('RPC response:', data);
      return data;
    } catch (err) {
      console.error('Error updating userwords:', err);
      throw err;
    }
  };

  return { addWordsToUserwords };
};
