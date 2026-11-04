// The web Videos page's payloads (GET /api/home, apps/api/home.py) and the
// small pure helpers its components share.

export const LEVELS = ['A1', 'A2', 'B1', 'B2', 'C1'] as const;
export type Level = (typeof LEVELS)[number];

export const LENGTHS = {
  any: 'Any length',
  short: 'Under 10 min',
  medium: '10–20 min',
  long: 'Over 20 min',
} as const;
export type LengthBand = keyof typeof LENGTHS;

export const ALL = 'All';
export const FOLLOWING = 'Following';
// Not a topic: the videos marked watched, each with Unmark (useWatchedVideos).
export const WATCHED = 'Watched';

export interface HomeVideo {
  id: string;
  title: string;
  channel: string | null;
  duration_s: number | null;
  understood: number;
  new_words: number;
  watched_share: number | null;
}

export interface Shelf {
  count: number;
  videos: HomeVideo[];
}

export interface HomeEmpty {
  nearest_level: Level | null;
  nearest: Shelf | null;
  other: Shelf | null;
}

export interface HomeChannel {
  name: string;
  channel_id: string | null;
  following: boolean;
  understood: number;
  videos: number;
  best: HomeVideo[];
  because: string | null;      // the followed or watched channel it is most like
}

/** What Channels you might like rests on. */
export interface ChannelBasis {
  following: string[];         // the favourite channels' names
  watched: number;             // videos watched from the library
}

export interface HomePage {
  videos: HomeVideo[];
  total: number;
  topics: string[];
  levels: Record<Level, number> | null;
  empty: HomeEmpty | null;
  channels: HomeChannel[];
  basis: ChannelBasis | null;  // null where the section isn't shown
}

export interface HomeFilters {
  topic: string;
  grammar: Level | null;
  length: LengthBand;
  q: string;
}

export const DEFAULT_FILTERS: HomeFilters = { topic: ALL, grammar: null, length: 'any', q: '' };

export function homeQuery(language: string, filters: HomeFilters): string {
  const params = new URLSearchParams({ language, topic: filters.topic, length: filters.length });
  if (filters.grammar) params.set('grammar', filters.grammar);
  if (filters.q.trim()) params.set('q', filters.q.trim());
  return `/api/home?${params}`;
}

/** 22:28, or 1:02:03 past an hour. */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${rest}` : `${m}:${rest}`;
}

export function minutes(seconds: number): number {
  return Math.max(1, Math.round(seconds / 60));
}

/** "watched 9 of 22 min", or "watched 40%" for a video without a length. */
export function watchedText(share: number, seconds: number | null): string {
  if (!seconds) return `watched ${Math.round(share * 100)}%`;
  return `watched ${Math.min(minutes(seconds), Math.round((share * seconds) / 60))} of ${minutes(seconds)} min`;
}

export function percent(understood: number): string {
  return `${Math.floor(understood)}%`;
}

export function youtubeUrl(videoId: string): string {
  return `https://www.youtube.com/watch?v=${videoId}`;
}

/** A title short enough for the pill: up to its first colon, or 40 characters. */
export function shortTitle(title: string): string {
  const head = title.split(/\s*[:|]\s/)[0].trim();
  return head.length <= 40 ? head : `${head.slice(0, 39).trimEnd()}…`;
}

// The video the learner left for, so the page can say what happened there
// when they come back. sessionStorage: it is this tab's trip.
const AWAY_KEY = 'langfour-home-away';

export interface Away {
  videoId: string;
  title: string;
  leftAt: string;
}

export function saveAway(away: Away): void {
  try {
    sessionStorage.setItem(AWAY_KEY, JSON.stringify(away));
  } catch {
    // Private mode or storage off: the page just won't say what was saved.
  }
}

export function takeAway(): Away | null {
  try {
    const raw = sessionStorage.getItem(AWAY_KEY);
    sessionStorage.removeItem(AWAY_KEY);
    const away = raw ? (JSON.parse(raw) as Away) : null;
    return away && typeof away.videoId === 'string' && typeof away.leftAt === 'string' ? away : null;
  } catch {
    return null;
  }
}

export function peekAway(): Away | null {
  try {
    const raw = sessionStorage.getItem(AWAY_KEY);
    return raw ? (JSON.parse(raw) as Away) : null;
  } catch {
    return null;
  }
}
