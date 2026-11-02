// How well the user would follow YouTube videos, for the thumbnail badges
// (youtubeFit.ts), as POST /api/videos/fit answers it, and the background's
// cache of those answers.
//
// The cache is per user and language and keeps an answer for 12 hours, so
// scrolling back or reopening Home costs nothing. Any change to the user's
// words clears it (clearVideoFits), since every percentage depends on them;
// the content script sees the clear and asks again.
import type { BackendResponse } from './messages';

export type VideoFit =
  | { status: 'scored'; percentUnderstood: number; newWords: number }
  // queued: what "+ Add" got back, so the card says so after a reload.
  | { status: 'unindexed'; queued?: QueueStatus }
  // Indexed but never recommended (garbled, a clip): no number.
  | { status: 'hidden' }
  // Not indexed, and YouTube says it is in another language: no "+ Add".
  | { status: 'other_language'; language: string };

// other_language: YouTube said so only when "+ Add" asked, and it wasn't queued.
export type QueueStatus = 'pending' | 'processing' | 'done' | 'failed' | 'skipped' | 'other_language';

export type VideoFitResponse = { ok: true; videos: Record<string, VideoFit> } | { ok: false; error: string };
export type QueueVideoResponse = { ok: true; status: QueueStatus } | { ok: false; error: string };

export const FIT_CACHE_KEY = 'videoFit';
export const FIT_MAX_AGE_MS = 12 * 60 * 60 * 1000;
/** Ids per request; the API takes at most this many. */
export const FIT_BATCH = 50;

const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;

type Entry = { fit: VideoFit; at: number };
export type StoredFits = {
  userId: string;
  language: string;
  entries: Record<string, Entry>;
  /** Set by a clear. An answer asked for before it is not stored. */
  clearedAt: number;
};

type Request = (path: string, body: unknown) => Promise<BackendResponse>;

async function readStored(): Promise<StoredFits | undefined> {
  const { [FIT_CACHE_KEY]: stored } = await chrome.storage.local.get(FIT_CACHE_KEY);
  return stored as StoredFits | undefined;
}

/** The stored answers that are this user's and language's and still fresh. */
function freshEntries(stored: StoredFits | undefined, userId: string, language: string, now: number) {
  if (!stored || stored.userId !== userId || stored.language !== language) return {};
  return Object.fromEntries(
    Object.entries(stored.entries).filter(([, entry]) => now - entry.at < FIT_MAX_AGE_MS),
  );
}

async function store(userId: string, language: string, fits: Record<string, VideoFit>, askedAt: number): Promise<void> {
  // Read again: another tab may have stored or cleared since this one asked.
  const stored = await readStored();
  const clearedAt = stored?.clearedAt ?? 0;
  if (clearedAt >= askedAt) return;
  const now = Date.now();
  const entries = freshEntries(stored, userId, language, now);
  for (const [id, fit] of Object.entries(fits)) entries[id] = { fit, at: now };
  const next: StoredFits = { userId, language, entries, clearedAt };
  await chrome.storage.local.set({ [FIT_CACHE_KEY]: next });
}

/** Fits for `videoIds`, from the cache where it has them, else from the API. */
export async function videoFits(
  language: string,
  videoIds: string[],
  userId: string,
  request: Request,
): Promise<VideoFitResponse> {
  const askedAt = Date.now();
  const ids = [...new Set(videoIds.filter((id) => VIDEO_ID.test(id)))];
  const cached = freshEntries(await readStored(), userId, language, askedAt);
  const videos: Record<string, VideoFit> = {};
  const missing: string[] = [];
  for (const id of ids) {
    if (cached[id]) videos[id] = cached[id].fit;
    else missing.push(id);
  }

  const fetched: Record<string, VideoFit> = {};
  for (let i = 0; i < missing.length; i += FIT_BATCH) {
    const response = await request('/api/videos/fit', { language, video_ids: missing.slice(i, i + FIT_BATCH) });
    if (!response.ok) return { ok: false, error: response.statusText || `HTTP ${response.status}` };
    try {
      Object.assign(fetched, (JSON.parse(response.body) as { videos: Record<string, VideoFit> }).videos);
    } catch {
      return { ok: false, error: 'Unreadable answer' };
    }
  }
  if (Object.keys(fetched).length) await store(userId, language, fetched, askedAt);
  return { ok: true, videos: { ...videos, ...fetched } };
}

/** Queues a video the corpus doesn't have, and remembers that it was. */
export async function queueVideo(
  language: string,
  videoId: string,
  userId: string,
  request: Request,
): Promise<QueueVideoResponse> {
  if (!VIDEO_ID.test(videoId)) return { ok: false, error: 'Not a video id' };
  const askedAt = Date.now();
  const response = await request('/api/videos/queue', { language, video_id: videoId });
  if (!response.ok) return { ok: false, error: response.statusText || `HTTP ${response.status}` };
  let status: QueueStatus;
  try {
    status = (JSON.parse(response.body) as { status: QueueStatus }).status;
  } catch {
    return { ok: false, error: 'Unreadable answer' };
  }
  await store(userId, language, { [videoId]: { status: 'unindexed', queued: status } }, askedAt);
  return { ok: true, status };
}

/** The user's words changed, or someone else signed in: every number is stale. */
export async function clearVideoFits(): Promise<void> {
  const cleared: StoredFits = { userId: '', language: '', entries: {}, clearedAt: Date.now() };
  await chrome.storage.local.set({ [FIT_CACHE_KEY]: cleared });
}
