import { useContext, useEffect, useState } from 'react';
import { supabase } from '@/lib/supabaseclient';
import { UserContext } from '@/context/UserContext';

export type ReviewProvider = 'langfour' | 'remnote';

type ReviewSettings = {
  provider: ReviewProvider | null;
  /** Where reviews happen in RemNote: the notes of the language being learned. */
  remnoteUrl: string | null;
};
const LOADING: ReviewSettings = { provider: null, remnoteUrl: null };

const REM_ID = /^[A-Za-z0-9_-]{1,64}$/;
const remId = (value: unknown) => (typeof value === 'string' && REM_ID.test(value) ? value : null);

/** The language's document (Langfour/Spanish), else the Langfour document,
 *  else RemNote itself until the plugin has synced once. */
export function remnoteDocumentUrl(rootRemId: unknown, languageRemIds: unknown, language: string | undefined): string {
  const byLanguage = languageRemIds && typeof languageRemIds === 'object' ? (languageRemIds as Record<string, unknown>) : {};
  const id = (language && remId(byLanguage[language])) || remId(rootRemId);
  return id ? `https://www.remnote.com/document/${id}` : 'https://www.remnote.com/';
}

type Row = { review_provider?: unknown; remnote_root_rem_id?: unknown; remnote_language_rem_ids?: unknown };

/** Read scheduling and the RemNote documents together under RLS. */
export const useReviewProvider = (): ReviewSettings => {
  const { user, language } = useContext(UserContext);
  const userId = user?.id;
  const [settings, setSettings] = useState<{ userId: string; row: Row | null } | null>(null);

  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    supabase
      .from('userdata')
      .select('review_provider, remnote_root_rem_id, remnote_language_rem_ids')
      .eq('user_id', userId)
      .maybeSingle()
      .then(({ data, error }) => {
        if (cancelled) return;
        if (error) console.error('Could not read review settings:', error);
        setSettings({ userId, row: data });
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  // Do not show the previous account's document while the next read is pending.
  if (!settings || settings.userId !== userId) return LOADING;
  const { row } = settings;
  const provider = row?.review_provider === 'remnote' ? 'remnote' : 'langfour';
  return {
    provider,
    remnoteUrl: provider === 'remnote'
      ? remnoteDocumentUrl(row?.remnote_root_rem_id, row?.remnote_language_rem_ids, language?.code)
      : null,
  };
};
