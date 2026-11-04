import { useCallback, useContext, useEffect, useRef, useState } from 'react';
import { UserContext } from '@/context/UserContext';
import { homeQuery, type HomeFilters, type HomePage } from '../components/home/homeApi';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
// Past this, a topic already seen is fetched again.
const PAGE_TTL_MS = 5 * 60_000;

/**
 * The Videos page (GET /api/home) for these filters in the sidebar's
 * language. Pages already fetched come back at once, so going back to a topic
 * costs nothing, and `prefetch` fetches one before it is asked for. The first
 * request of a visit reads the learner's data; the rest ask the server to
 * reuse it (`reuse=1`). `reload` starts over, for coming back from YouTube.
 */
export function useHome(filters: HomeFilters) {
  const { fetchWithAuth, language } = useContext(UserContext);
  const code = language?.code;
  const key = code ? homeQuery(code, filters) : null;
  const [pages, setPages] = useState<Record<string, HomePage>>({});
  const [failed, setFailed] = useState<string | null>(null);
  const [lastPage, setLastPage] = useState<HomePage | null>(null);
  const [tick, setTick] = useState(0);
  const inFlight = useRef(new Map<string, Promise<void>>());
  const generation = useRef(0);
  const readAgain = useRef(true);

  const fetchPage = useCallback(
    (pageKey: string): Promise<void> => {
      const running = inFlight.current.get(pageKey);
      if (running) return running;
      const started = generation.current;
      const reuse = !readAgain.current;
      readAgain.current = false;
      const request = (async () => {
        const response = await fetchWithAuth(`${API_URL}${pageKey}${reuse ? '&reuse=1' : ''}`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const page = (await response.json()) as HomePage;
        // Asked before a reload: it may show what the reload is there to replace.
        if (started === generation.current) setPages((known) => ({ ...known, [pageKey]: page }));
      })().finally(() => {
        if (inFlight.current.get(pageKey) === request) inFlight.current.delete(pageKey);
      });
      inFlight.current.set(pageKey, request);
      return request;
    },
    [fetchWithAuth],
  );

  /** Forget what was fetched and have the server read it all again. `keep`
   * stays up, for a page that is right as it is. */
  const startOver = useCallback((keep: string | null) => {
    generation.current += 1;
    readAgain.current = true;
    inFlight.current.clear();
    setPages((known) => (keep && known[keep] ? { [keep]: known[keep] } : {}));
  }, []);

  const current = key ? pages[key] : undefined;
  const loaded = Boolean(current);

  useEffect(() => {
    if (!key || loaded) return;
    fetchPage(key)
      .then(() => setFailed((was) => (was === key ? null : was)))
      .catch((err) => {
        console.error(err);
        setFailed(key);
      });
  }, [key, loaded, tick, fetchPage]);

  useEffect(() => {
    const id = setInterval(() => startOver(key), PAGE_TTL_MS);
    return () => clearInterval(id);
  }, [key, startOver]);

  // The last page stays up while the next one loads.
  if (current && current !== lastPage) setLastPage(current);
  const page = current ?? lastPage;
  const error = failed === key ? 'Could not load videos. Please try again later.' : null;
  const loading = !current && !error;

  const reload = useCallback(() => {
    startOver(null);
    setTick((t) => t + 1);
  }, [startOver]);

  /** Fetch these filters' page ahead of a click. Failing is fine: the click asks again. */
  const prefetch = useCallback(
    (change: Partial<HomeFilters>) => {
      if (!code) return;
      const next = homeQuery(code, { ...filters, ...change });
      if (next !== key && !pages[next]) fetchPage(next).catch(() => {});
    },
    [code, filters, key, pages, fetchPage],
  );

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
      // What it suggests rests on who they follow. This page stays as it is,
      // so the row they just clicked doesn't move away.
      startOver(key);
    },
    [code, key, post, startOver],
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

  return { page, loading, error, reload, prefetch, setHidden, setFollowing, cameBack, language: code };
}
