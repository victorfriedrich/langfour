import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { BackendResponse } from './messages';
import { clearVideoFits, FIT_CACHE_KEY, FIT_MAX_AGE_MS, queueVideo, StoredFits, videoFits } from './videoFit';

const A = 'aaaaaaaaaaa';
const B = 'bbbbbbbbbbb';
const ok = (body: unknown): BackendResponse => ({ ok: true, status: 200, statusText: 'OK', body: JSON.stringify(body) });
const stored = () => (chrome.storage.local as unknown as { __store: Map<string, unknown> }).__store.get(FIT_CACHE_KEY) as StoredFits;

function api() {
  const asked: { path: string; body: { video_ids?: string[]; video_id?: string } }[] = [];
  const request = vi.fn(async (path: string, body: unknown) => {
    asked.push({ path, body: body as { video_ids?: string[] } });
    if (path === '/api/videos/queue') return ok({ status: 'pending' });
    const ids = (body as { video_ids: string[] }).video_ids;
    return ok({ videos: Object.fromEntries(ids.map((id) => [id, { status: 'scored', percentUnderstood: 97.4, newWords: 12 }])) });
  });
  return { asked, request };
}

describe('videoFits', () => {
  beforeEach(() => vi.useRealTimers());

  it('asks the API once per video and answers from the cache after', async () => {
    const { asked, request } = api();
    const first = await videoFits('es', [A, B, A], 'user-1', request);
    expect(first).toEqual({ ok: true, videos: {
      [A]: { status: 'scored', percentUnderstood: 97.4, newWords: 12 },
      [B]: { status: 'scored', percentUnderstood: 97.4, newWords: 12 },
    } });
    await videoFits('es', [A, B], 'user-1', request);
    expect(asked).toEqual([{ path: '/api/videos/fit', body: { language: 'es', video_ids: [A, B] } }]);
  });

  it('keeps answers per user and language, for 12 hours', async () => {
    const { asked, request } = api();
    await videoFits('es', [A], 'user-1', request);
    await videoFits('es', [A], 'user-2', request);
    await videoFits('de', [A], 'user-2', request);
    expect(asked).toHaveLength(3);

    vi.useFakeTimers({ now: Date.now() + FIT_MAX_AGE_MS + 1 });
    await videoFits('de', [A], 'user-2', request);
    expect(asked).toHaveLength(4);
  });

  it('asks in batches of 50 and drops what is not a video id', async () => {
    const { asked, request } = api();
    const ids = Array.from({ length: 120 }, (_, i) => `video${String(i).padStart(6, '0')}`);
    await videoFits('es', [...ids, 'not-an-id'], 'user-1', request);
    expect(asked.map((a) => a.body.video_ids!.length)).toEqual([50, 50, 20]);
  });

  it('starts over after a clear, and drops answers asked for before it', async () => {
    const { asked, request } = api();
    await videoFits('es', [A], 'user-1', request);
    await clearVideoFits();
    await videoFits('es', [A], 'user-1', request);
    expect(asked).toHaveLength(2);

    // An answer that arrives after a clear is from before the change.
    let release!: () => void;
    const slow = vi.fn(async (path: string, body: unknown) => {
      await new Promise<void>((resolve) => (release = resolve));
      return request(path, body);
    });
    const pending = videoFits('es', [B], 'user-1', slow);
    await vi.waitFor(() => expect(release).toBeDefined());
    await new Promise((resolve) => setTimeout(resolve, 2));
    await clearVideoFits();
    release();
    expect((await pending).ok).toBe(true);
    expect(stored().entries).toEqual({});
  });

  it('reports a failed request rather than caching it', async () => {
    const request = vi.fn(async () => ({ ok: false, status: 401, statusText: 'No Supabase session available', body: '' }));
    expect(await videoFits('es', [A], 'user-1', request)).toEqual({ ok: false, error: 'No Supabase session available' });
    expect(stored()).toBeUndefined();
  });
});

describe('queueVideo', () => {
  it('queues the video and remembers it was queued', async () => {
    const { asked, request } = api();
    expect(await queueVideo('es', A, 'user-1', request)).toEqual({ ok: true, status: 'pending' });
    expect(asked).toEqual([{ path: '/api/videos/queue', body: { language: 'es', video_id: A } }]);
    expect((await videoFits('es', [A], 'user-1', request)).ok && stored().entries[A].fit)
      .toEqual({ status: 'unindexed', queued: 'pending' });
    expect(asked).toHaveLength(1);
  });
});
