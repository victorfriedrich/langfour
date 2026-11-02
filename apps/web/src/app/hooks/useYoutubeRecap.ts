import { useCallback, useContext, useEffect, useState } from 'react';
import { UserContext } from '@/context/UserContext';
import { recapPath, type Recap } from '../../../../extension/src/youtubeRecap';

/**
 * Yesterday's YouTube recap in the sidebar's language (apps/api/watch.py),
 * or null while loading and when there is nothing to show.
 */
export const useYoutubeRecap = () => {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  const { fetchWithAuth, user, language } = useContext(UserContext);
  const code = language?.code;
  const [recap, setRecap] = useState<Recap | null>(null);

  useEffect(() => {
    if (!user || user.is_anonymous || !code) return;
    let cancelled = false;
    (async () => {
      try {
        const response = await fetchWithAuth(`${API_URL}${recapPath(code)}`);
        if (!response.ok) return;
        const data = (await response.json()) as Recap;
        if (!cancelled) setRecap(data.words.length ? data : null);
      } catch {
        // No recap is fine: it's replaced tomorrow.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [API_URL, fetchWithAuth, user, code]);

  const add = useCallback(
    async (words: { word_id: number; video_id: string }[]) => {
      const response = await fetchWithAuth(`${API_URL}/api/watch/recap/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language: code, words }),
      });
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      return ((await response.json()) as { added: string[] }).added;
    },
    [API_URL, fetchWithAuth, code],
  );

  const close = useCallback(async () => {
    if (!recap) return;
    setRecap(null);
    await fetchWithAuth(`${API_URL}/api/watch/recap/close`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ day: recap.day }),
    });
  }, [API_URL, fetchWithAuth, recap]);

  return { recap, add, close };
};
