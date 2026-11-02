import { useCallback, useContext, useEffect, useState } from 'react';
import { UserContext } from '@/context/UserContext';

export interface WatchedVideo {
  video_id: string;
  title: string | null;
  watched_at: string;
  source: 'desktop' | 'history' | 'manual';
}

/**
 * The videos marked watched in the sidebar's language, newest first
 * (GET /api/watch): played to 70% on desktop, read from the YouTube history
 * page, or hidden here by hand. Unmark takes one off, so it shows up in the
 * recommendations again and can be watched again.
 */
export const useWatchedVideos = (enabled: boolean) => {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  const { fetchWithAuth, user, language } = useContext(UserContext);
  const code = language?.code;
  const [videos, setVideos] = useState<WatchedVideo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || !user || user.is_anonymous || !code) return;
    let cancelled = false;
    (async () => {
      try {
        const response = await fetchWithAuth(`${API_URL}/api/watch?language=${code}`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        if (!cancelled) setVideos(data.videos);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load watched videos');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [API_URL, fetchWithAuth, user, code, enabled]);

  const unmark = useCallback(
    async (videoId: string) => {
      const response = await fetchWithAuth(`${API_URL}/api/watch/unmark`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_id: videoId }),
      });
      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
      setVideos((prev) => prev && prev.filter((v) => v.video_id !== videoId));
    },
    [API_URL, fetchWithAuth],
  );

  return { videos, error, unmark };
};
