import { useState } from 'react';
// Must be the shared client. createBrowserClient (@supabase/ssr) keeps its
// session in document.cookie, but the session is written to localStorage by
// the supabase-js client in @/lib/supabaseclient — nothing in this app writes
// the auth cookie. A client built here would therefore have no session and
// call the RPC as `anon`, so add_custom_translation would insert a row with
// user_id = auth.uid() = NULL.
import { supabase } from '@/lib/supabaseclient';

interface CustomTranslationParams {
  customTranslation: string;
  userId: string;
  wordId: number;
}

export const useCustomTranslation = () => {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const addCustomTranslation = async ({
    customTranslation,
    userId,
    wordId,
  }: CustomTranslationParams) => {
    setIsLoading(true);
    setError(null);

    try {
      let { data, error } = await supabase.rpc('add_custom_translation', {
        _custom_translation: customTranslation, 
        _word_id: wordId
      });
      if (error) {
        console.error('Error adding custom translation:', error);
        setError(error.message);
      } else {
        console.log('Custom translation added successfully:', data);
      }
    } catch (err) {
      console.error('Unexpected error:', err);
      setError('An unexpected error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  return { addCustomTranslation, isLoading, error };
};
