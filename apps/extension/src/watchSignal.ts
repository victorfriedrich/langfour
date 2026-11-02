// Desktop watching on youtube.com (docs/plans/youtube-plan.md, feature 2):
// the seconds of a video actually played, and at 70% the video is marked
// watched (POST /api/watch). Only videos in Langfour's index for the
// learning language count; the API says which when a video opens.
//
// Runs in the content script's isolated world, apart from index.ts and the
// thumbnail badges, so it touches nothing on the page.

import { getPrefs } from './preferencePopup/prefs';
import { sendToBackground } from './messages';
import type { WatchState } from './messages';

export const WATCHED_SHARE = 0.7;
const TICK_MS = 1000;
// A jump bigger than this between two ticks is a seek, not playback (two
// seconds of video per second at 2x, with room for a late tick).
const MAX_STEP_S = 3;
const SAVE_EVERY_TICKS = 10;
const STORAGE_PREFIX = 'langfour-played:';

/** The whole seconds of a video that played, each counted once. */
export class PlayedSeconds {
  private seconds: Set<number>;

  constructor(seconds: Iterable<number> = []) {
    this.seconds = new Set(seconds);
  }

  /** Playback moved from `from` to `to` (seconds into the video). */
  add(from: number, to: number): void {
    if (!(to > from) || to - from > MAX_STEP_S) return;
    for (let s = Math.floor(from); s < Math.floor(to); s++) this.seconds.add(s);
  }

  share(duration: number): number {
    if (!(duration > 0)) return 0;
    return Math.min(1, this.seconds.size / Math.ceil(duration));
  }

  toJSON(): number[] {
    return Array.from(this.seconds);
  }
}

export function watchVideoId(href: string): string | null {
  try {
    const url = new URL(href);
    if (url.pathname !== '/watch') return null;
    const id = url.searchParams.get('v');
    return id && /^[A-Za-z0-9_-]{11}$/.test(id) ? id : null;
  } catch {
    return null;
  }
}

function language(): Promise<string> {
  return new Promise((resolve) => getPrefs((prefs) => resolve(prefs.preferredLanguage)));
}

function ask<T>(message: Parameters<typeof sendToBackground>[0]): Promise<T | undefined> {
  return new Promise((resolve) => {
    try {
      sendToBackground<T>(message, (response) => resolve(chrome.runtime.lastError ? undefined : response));
    } catch {
      resolve(undefined); // the extension was reloaded under this page
    }
  });
}

// Kept in the tab's sessionStorage, so a reload doesn't start the count over.
function load(videoId: string): PlayedSeconds {
  try {
    return new PlayedSeconds(JSON.parse(sessionStorage.getItem(STORAGE_PREFIX + videoId) ?? '[]'));
  } catch {
    return new PlayedSeconds();
  }
}

function save(videoId: string, played: PlayedSeconds): void {
  try {
    sessionStorage.setItem(STORAGE_PREFIX + videoId, JSON.stringify(played));
  } catch {
    // Full or blocked: the count lives on in memory.
  }
}

function forget(videoId: string): void {
  try {
    sessionStorage.removeItem(STORAGE_PREFIX + videoId);
  } catch {
    // nothing kept
  }
}

export function watchDesktop(): void {
  let state: WatchState = { videoId: null, indexed: false, watched: false, share: 0 };
  let played = new PlayedSeconds();
  let last: number | null = null;
  let ticks = 0;
  let checking: string | null = null;
  let lang = '';

  const check = async (videoId: string) => {
    checking = videoId;
    lang = await language();
    const answer = await ask<{ indexed: boolean; watched: boolean }>({ type: 'WATCH_STATUS', videoId, language: lang });
    if (checking !== videoId) return; // moved on meanwhile
    checking = null;
    played = load(videoId);
    state = { videoId, indexed: !!answer?.indexed, watched: !!answer?.watched, share: state.share };
  };

  const open = (videoId: string | null) => {
    if (state.videoId && state.videoId !== videoId) save(state.videoId, played);
    state = { videoId, indexed: false, watched: false, share: 0 };
    played = new PlayedSeconds();
    last = null;
    if (videoId) void check(videoId);
  };

  setInterval(() => {
    const videoId = watchVideoId(location.href);
    if (videoId !== state.videoId) open(videoId);
    if (!videoId || !state.indexed || state.watched || checking) return;

    const player = document.querySelector('#movie_player');
    const video = document.querySelector<HTMLVideoElement>('#movie_player video');
    // Ads play in the same <video>; they are not the video.
    const playing = video && !video.paused && !video.ended && !video.seeking &&
      !player?.classList.contains('ad-showing');
    if (!video || !playing) {
      last = null;
      return;
    }
    if (last !== null) played.add(last, video.currentTime);
    last = video.currentTime;
    state.share = played.share(video.duration);
    if (++ticks % SAVE_EVERY_TICKS === 0) save(videoId, played);

    if (state.share >= WATCHED_SHARE) {
      state.watched = true; // once, even if the call fails
      void ask({ type: 'WATCH_MARK', videoId, share: Math.round(state.share * 100) / 100, language: lang })
        .then(() => forget(videoId));
    }
  }, TICK_MS);

  window.addEventListener('pagehide', () => {
    if (state.videoId && !state.watched) save(state.videoId, played);
  });

  // The popup asks what this tab is playing, and unmarks it. After an
  // unmark the count starts again from nothing: a retry needs its own 70%.
  chrome.runtime.onMessage.addListener((message: { type?: string }, _sender, sendResponse) => {
    if (message?.type === 'WATCH_STATE') {
      sendResponse(state.videoId ? state : null);
      return;
    }
    if (message?.type === 'WATCH_RESET' && state.videoId) {
      forget(state.videoId);
      played = new PlayedSeconds();
      last = null;
      state = { ...state, watched: false, share: 0 };
      sendResponse(state);
    }
  });

  // Another learning language: whether this video counts may change.
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'sync' && changes.preferredLanguage && state.videoId) void check(state.videoId);
  });
}
