import { useState, useEffect } from 'react';
import { supabase } from '@/lib/supabaseclient';

export const useUserLanguages = () => {
  const [userLanguages, setUserLanguages] = useState<string[]>([]);
  const [defaultLanguage, setDefaultLanguage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const fetchUserLanguages = async () => {
    try {
      setIsLoading(true);
      // Fetch available languages
      const { data: languagesData, error: languagesError } = await supabase.rpc('get_available_languages');
      if (languagesError) throw languagesError;
      
      // Fetch default language
      const { data: defaultLangData, error: defaultLangError } = await supabase.rpc('get_user_default_language');
      if (defaultLangError) throw defaultLangError;
      
      setUserLanguages(languagesData || []);
      setDefaultLanguage(defaultLangData);
    } catch (err) {
      console.error('Error fetching user languages:', err);
      setError(err instanceof Error ? err : new Error('Failed to fetch user languages'));
    } finally {
      setIsLoading(false);
    }
  };

  const setUserDefaultLanguage = async (languageCode: string): Promise<boolean> => {
    try {
      await supabase.rpc('set_user_default_language', { _language: languageCode });
      setDefaultLanguage(languageCode);
      return true;
    } catch (err) {
      console.error('Error setting default language:', err);
      return false;
    }
  };

  // Driven by auth state rather than mount. Both RPCs read auth.uid(), so
  // signed out there is nothing to fetch — and once RLS is on they return
  // 42501 rather than an empty result, which this hook would surface as an
  // error on every visit to /login. onAuthStateChange emits INITIAL_SESSION
  // to each new subscriber once the stored session has been restored, so this
  // still fires exactly once on a normal signed-in page load.
  useEffect(() => {
    // undefined = not yet known, so the first event always runs.
    let seenUserId: string | null | undefined = undefined;

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      const userId = session?.user?.id ?? null;
      // TOKEN_REFRESHED fires periodically for the same user; don't refetch.
      if (userId === seenUserId) return;
      seenUserId = userId;

      if (!userId) {
        setUserLanguages([]);
        setDefaultLanguage(null);
        setError(null);
        setIsLoading(false);
        return;
      }

      fetchUserLanguages();
    });

    return () => subscription.unsubscribe();
  }, []);

  return { 
    userLanguages, 
    defaultLanguage, 
    isLoading, 
    error, 
    fetchUserLanguages, 
    setUserDefaultLanguage 
  };
};
