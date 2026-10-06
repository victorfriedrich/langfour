import { useContext, useEffect, useState } from 'react';
import { supabase } from '@/lib/supabaseclient';
import { UserContext } from '@/context/UserContext';

export type ReviewProvider = 'langfour' | 'remnote';

type ReviewSettings = {
  provider: ReviewProvider | null;
  remnoteDocumentUrl: string | null;
};
const LOADING: ReviewSettings = { provider: null, remnoteDocumentUrl: null };

/** Read scheduling and the optional document shortcut together under RLS.
 * Linked flashcards can live outside that document, so it is never the only
 * way to open RemNote reviews. */
export const useReviewProvider = (): ReviewSettings => {
  const { user } = useContext(UserContext);
  const userId = user?.id;
  const [settings, setSettings] = useState<ReviewSettings & { userId: string } | null>(null);

  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    supabase
      .from('userdata')
      .select('review_provider, remnote_root_rem_id')
      .eq('user_id', userId)
      .maybeSingle()
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) console.error('Could not read review settings:', error);
        const provider = data?.review_provider === 'remnote' ? 'remnote' : 'langfour';
        const rootRemId = data?.remnote_root_rem_id;
        setSettings({
          userId,
          provider,
          remnoteDocumentUrl: provider === 'remnote' && typeof rootRemId === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(rootRemId)
            ? `https://www.remnote.com/flashcards/${rootRemId}`
            : null,
        });
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  // Do not show the previous account's document while the next read is pending.
  return settings?.userId === userId && settings ? settings : LOADING;
};
