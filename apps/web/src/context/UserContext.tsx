'use client';

import React, {
  createContext,
  useCallback,
  useState,
  useEffect,
  ReactNode,
} from 'react';
import { supabase } from '@/lib/supabaseclient';
import { useUserLanguages } from '@/app/hooks/useUserLanguages';
import { useInitializeAccount } from '@/app/hooks/useInitializeAccount';
import { LANGUAGES, LANGUAGE_LIST, getLanguage, toLanguageCode } from '@/lib/languages';

interface UserProfile {
  id: string;
  email: string | null;
  is_anonymous: boolean;
  // Add other profile fields as needed
}

export interface LanguageOption {
  code: string;
  name: string;
  flag: string;
}

export interface AvailableLanguageOption extends LanguageOption {
  initialized: boolean;
}

interface UserContextProps {
  user: UserProfile | null;
  fetchWithAuth: (url: string, options?: RequestInit) => Promise<Response>;
  loading: boolean;
  language: LanguageOption | null;
  availableLanguages: AvailableLanguageOption[];
  setLanguage: (language: LanguageOption) => void;
  initializeLanguage: (language: string, languageLevel: string) => Promise<void>;
}

export const UserContext = createContext<UserContextProps>({
  user: null,
  fetchWithAuth: async () => new Response(),
  loading: true,
  language: null,
  availableLanguages: [],
  setLanguage: () => {},
  initializeLanguage: async () => {},
});

export const UserProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [language, setLanguageState] = useState<LanguageOption | null>(null);

  // The localStorage read stays in a useEffect, not a useState initializer:
  // 968bb9a moved it here because the server always rendered null while the
  // client's first render returned the stored language, causing a hydration
  // mismatch in the Sidebar language selector. Only the lookup changes --
  // getLanguage() also accepts a legacy long name, which browsers may still
  // hold from before the ISO cutover.
  useEffect(() => {
    const stored = getLanguage(localStorage.getItem('selected-language'));
    if (stored) {
      setLanguageState({ ...stored });
    }
  }, []);

  const { userLanguages, defaultLanguage, isLoading: languagesLoading, fetchUserLanguages, setUserDefaultLanguage } = useUserLanguages();
  const { initializeUserAccount } = useInitializeAccount();
  const [availableLanguages, setAvailableLanguages] = useState<AvailableLanguageOption[]>([]);

  useEffect(() => {
    const getUser = async () => {
      setLoading(true);
      const { data: { session } } = await supabase.auth.getSession();
      
      const currentUser = session?.user ? {
        id: session.user.id,
        email: session.user.email,
        is_anonymous: session.user.is_anonymous,
      } : null;
      
      setUser(currentUser);

      const { data: authListener } = supabase.auth.onAuthStateChange((_event, session) => {
        setUser(session?.user ? {
          id: session.user.id,
          email: session.user.email,
          is_anonymous: session.user.is_anonymous,
        } : null);
        setLoading(false);
      });

      setLoading(false);

      return () => {
        authListener.subscription.unsubscribe();
      };
    };

    getUser();
  }, []);

  useEffect(() => {
    // Process the user languages data to create the available languages list
    if (!languagesLoading) {
      // userLanguages may hold legacy long names for accounts created before
      // the ISO cutover, so compare on the normalised code rather than raw
      // strings. This keeps the selector correct whether or not the data
      // migration has been run yet.
      const initializedCodes = new Set(
        userLanguages.map(toLanguageCode).filter(Boolean)
      );
      const availableLangs: AvailableLanguageOption[] = LANGUAGE_LIST.map(lang => ({
        ...lang,
        initialized: initializedCodes.has(lang.code)
      }));

      setAvailableLanguages(availableLangs);

      const storedLang = typeof window !== 'undefined'
        ? getLanguage(localStorage.getItem('selected-language'))
        : null;
      const defaultLang = getLanguage(defaultLanguage);

      // If we have a default language set in the database, prefer it
      if (defaultLang) {
        setLanguageState({ ...defaultLang });
        if (typeof window !== 'undefined') {
          localStorage.setItem('selected-language', defaultLang.code);
        }
      } else if (!language && storedLang) {
        // Fallback to language stored locally if context not yet set
        setLanguageState({ ...storedLang });
      } else if (!language && availableLangs.some(l => l.initialized)) {
        // If user has any initialized language, set the first one
        const firstInitialized = availableLangs.find(l => l.initialized);
        if (firstInitialized) {
          setLanguageState(firstInitialized);
          if (typeof window !== 'undefined') {
            localStorage.setItem('selected-language', firstInitialized.code);
          }
        }
      } else if (!language) {
        // Default to first supported language if nothing is found
        const fallback = LANGUAGE_LIST[0];
        setLanguageState(fallback);
        if (typeof window !== 'undefined') {
          localStorage.setItem('selected-language', fallback.code);
        }
      }
    }
  }, [userLanguages, defaultLanguage, languagesLoading]);
  
  const fetchWithAuth = useCallback(async (url: string, options: RequestInit = {}) => {
    const { data: { session } } = await supabase.auth.getSession();
    const token = session?.access_token;
  
    if (!token) {
      throw new Error('No authentication token available');
    }
  
    const defaultHeaders: Record<string, string> = {
      Authorization: `Bearer ${token}`,
    };
  
    // Only add Content-Type if a body exists and it's not FormData
    if (options.body && !(options.body instanceof FormData)) {
      defaultHeaders['Content-Type'] = 'application/json';
    }
  
    const mergedOptions: RequestInit = {
      ...options,
      headers: {
        ...defaultHeaders,
        ...(options.headers as Record<string, string>),
      },
    };
  
    return fetch(url, mergedOptions);
  }, []);
  
  const handleSetLanguage = async (newLanguage: LanguageOption) => {
    setLanguageState(newLanguage);
    if (typeof window !== 'undefined') {
      localStorage.setItem('selected-language', newLanguage.code);
    }

    // Update default language in database if user is logged in and language is
    // initialized. Normalised for the same reason as above: a legacy account's
    // userLanguages may read ['spanish'] rather than ['es'].
    const initialized = userLanguages.some(l => toLanguageCode(l) === newLanguage.code);
    if (user && !user.is_anonymous && initialized) {
      await setUserDefaultLanguage(newLanguage.code);
    }
  };

  const initializeLanguage = async (language: string, languageLevel: string) => {
    try {
      await initializeUserAccount(language, languageLevel);
      // Refresh the user languages list
      await fetchUserLanguages();
    } catch (error) {
      console.error('Error initializing language:', error);
      throw error;
    }
  };

  return (
    <UserContext.Provider
      value={{ 
        user, 
        fetchWithAuth, 
        loading: loading || languagesLoading, 
        language, 
        availableLanguages,
        setLanguage: handleSetLanguage,
        initializeLanguage
      }}
    >
      {children}
    </UserContext.Provider>
  );
};