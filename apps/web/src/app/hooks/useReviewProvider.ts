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
