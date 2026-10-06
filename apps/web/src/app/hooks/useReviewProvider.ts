import { useContext, useEffect, useState } from 'react';
import { supabase } from '@/lib/supabaseclient';
import { UserContext } from '@/context/UserContext';

export type ReviewProvider = 'langfour' | 'remnote';

/**
 * Who schedules this user's reviews (userdata.review_provider, see
 * apps/api/sql/remnote_sync.sql). One column read under RLS, so pages that
 * only need this do not pay for the full RemNote connection status.
 * Null while loading.
 */
export const useReviewProvider = (): ReviewProvider | null => {
  const { user } = useContext(UserContext);
  const [provider, setProvider] = useState<ReviewProvider | null>(null);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    supabase
      .from('userdata')
      .select('review_provider')
      .eq('user_id', user.id)
      .maybeSingle()
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) console.error('Could not read review provider:', error);
        setProvider((data?.review_provider as ReviewProvider | undefined) ?? 'langfour');
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  return provider;
};

const REMNOTE_HOME = 'https://www.remnote.com/';

/** The review queue of the user's "Langfour" document in RemNote
 *  (userdata.remnote_root_rem_id, reported by the plugin), or RemNote's home
 *  page until the plugin has synced once. */
export const remnoteReviewUrl = (rootRemId: string | null | undefined): string =>
  rootRemId && /^[A-Za-z0-9_-]{1,64}$/.test(rootRemId)
    ? `https://www.remnote.com/flashcards/${rootRemId}`
    : REMNOTE_HOME;

export const useRemnoteReviewUrl = (): string => {
  const { user } = useContext(UserContext);
  const [url, setUrl] = useState(REMNOTE_HOME);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    supabase
      .from('userdata')
      .select('remnote_root_rem_id')
      .eq('user_id', user.id)
      .maybeSingle()
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) console.error('Could not read the RemNote document:', error);
        setUrl(remnoteReviewUrl(data?.remnote_root_rem_id as string | null | undefined));
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  return url;
};
