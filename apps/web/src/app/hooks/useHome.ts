import { useCallback, useContext, useEffect, useState } from 'react';
import { UserContext } from '@/context/UserContext';
import { homeQuery, type HomeFilters, type HomePage } from '../components/home/homeApi';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

/**
 * The Videos page (GET /api/home) for these filters in the sidebar's
 * language. A response for filters that have since changed is dropped.
 * `reload` fetches the same page again, for coming back from YouTube.
 */
export function useHome(filters: HomeFilters) {
  const { fetchWithAuth, language } = useContext(UserContext);
  const code = language?.code;
  const key = code ? homeQuery(code, filters) : null;
  const [result, setResult] = useState<{ key: string; page: HomePage | null; error: string | null } | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    (async () => {
      try {
        const response = await fetchWithAuth(`${API_URL}${key}`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const page = (await response.json()) as HomePage;
        if (!cancelled) setResult({ key, page, error: null });
      } catch (err) {
        console.error(err);
        if (!cancelled) {
          setResult((prev) => ({ key, page: prev?.page ?? null, error: 'Could not load videos. Please try again later.' }));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [key, tick, fetchWithAuth]);

  // The last page stays up while the next one loads.
  const page = result?.page ?? null;
  const loading = result?.key !== key;
  const error = result?.key === key ? result.error : null;
  const reload = useCallback(() => setTick((t) => t + 1), []);

  const post = useCallback(
    async (path: string, body: unknown) => {
      const response = await fetchWithAuth(`${API_URL}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      return response.json();
    },
    [fetchWithAuth],
  );

  /** Not interested, or Undo. Answers with the channel's name for `channel`. */
  const setHidden = useCallback(
    async (videoId: string, channel: boolean, hidden: boolean): Promise<string | null> => {
      if (!code) return null;
      const data = await post(hidden ? '/api/home/hide' : '/api/home/unhide', {
        language: code,
        video_id: videoId,
        channel,
      });
      return data.channel ?? null;
    },
    [code, post],
  );

  const setFollowing = useCallback(
    async (channelId: string, favourite: boolean) => {
      if (!code) return;
      await post(`/api/channels/${channelId}/favourite`, { language: code, favourite });
    },
    [code, post],
  );

  /** How far into a video the learner got and how many words they saved
   * from it since `since`. */
  const cameBack = useCallback(
    async (videoId: string, since: string): Promise<{ share: number | null; saved: number }> => {
      const params = new URLSearchParams({ video_id: videoId, since });
      const response = await fetchWithAuth(`${API_URL}/api/home/return?${params}`);
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      return response.json();
    },
    [fetchWithAuth],
  );

  return { page, loading, error, reload, setHidden, setFollowing, cameBack, language: code };
}
