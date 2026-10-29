import { supabase } from '@/lib/supabaseclient';

interface FlashcardTestParams {
  wordId: number;
  testType: 'flashcard' | 'typing';
  testResult: boolean;
}

export const useUpdateFlashCardInfo = () => {
  // testType (flashcard or typing) no longer changes anything: a Langfour
  // word has one card, which both kinds of test review.
  const updateFlashCardInfo = async ({
    wordId,
    testResult,
  }: FlashcardTestParams) => {

    try {
      // Records the answer and reschedules the word's Langfour card.
      const { error } = await supabase.rpc('update_spaced_repetition', {
        _test_result: testResult,
        _word_id: wordId,
      });
      if (error) {
        console.error('Error recording the review:', error);
        throw error;
      }
    } catch (err) {
      console.error('Unexpected error:', err);
      throw err;
    }
  };

  return { updateFlashCardInfo };
};


