// The user's YouTube history page, read by the background with their own
// sign-in (docs/plans/youtube-plan.md, feature 2). It is the one place on
// desktop that also lists what they watched in the YouTube app on a phone.
//
// Only after consent, given once per Google account on a card on youtube.com
// (historyPrompt.ts). The page
// is fetched, the video ids with their red progress bar and day are taken
// from the data YouTube embeds in it (ytInitialData), and those go to the
// API, which keeps the ones in Langfour's index for the user's language and
// drops the rest (apps/api/watch.py). Titles and channels are never read.
//
// The parsing here is free of the DOM and of chrome.*, so it can be tested
// against saved pages.

export const HISTORY_URL = 'https://www.youtube.com/feed/history';
export const HISTORY_ALARM = 'watch-history';
// Read at most this often: often enough for the next day's recap.
export const HISTORY_EVERY_MINUTES = 120;
const MAX_ITEMS = 500;

/** chrome.storage.local keys. */
export const HISTORY_CONSENT_KEY = 'historyConsent'; // Google account ids that said yes
export const HISTORY_DECLINED_KEY = 'historyDeclined'; // "Not now", until turned on
export const HISTORY_NEW_ACCOUNT_KEY = 'historyNewAccount'; // the account signed in, not asked yet
export const HISTORY_DECLINED_ACCOUNTS_KEY = 'historyDeclinedAccounts'; // new accounts that said "Not now"
export const HISTORY_LAST_READ_KEY = 'historyLastRead';

export type HistoryItem = { video_id: string; share: number | null; day: 0 | 1 | null };
export type HistoryPage = {
  /** The Google account (or brand account) signed in; null when signed out. */
  account: string | null;
  items: HistoryItem[];
};

const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;

/** The JSON assigned to `var ytInitialData` in the page's scripts. */
function initialData(html: string): unknown {
  const start = html.search(/(?:var |window\[["'])ytInitialData(?:["']\])?\s*=\s*\{/);
  if (start < 0) return null;
  const open = html.indexOf('{', start);
  // The object ends at the matching brace; strings may hold braces.
  let depth = 0;
  let inString = false;
  for (let i = open; i < html.length; i++) {
    const c = html[i];
    if (inString) {
      if (c === '\\') i++;
      else if (c === '"') inString = false;
    } else if (c === '"') inString = true;
    else if (c === '{') depth++;
    else if (c === '}' && --depth === 0) {
      try {
        return JSON.parse(html.slice(open, i + 1));
      } catch {
        return null;
      }
    }
  }
  return null;
}

function config(html: string, key: string): string | null {
  return html.match(new RegExp(`"${key}":\\s*"([^"]*)"`))?.[1] ?? null;
}

type Node = Record<string, unknown>;
const isNode = (v: unknown): v is Node => !!v && typeof v === 'object' && !Array.isArray(v);

function* walk(value: unknown): Generator<[string, unknown]> {
  if (Array.isArray(value)) {
    for (const v of value) yield* walk(v);
  } else if (isNode(value)) {
    for (const [k, v] of Object.entries(value)) {
      yield [k, v];
      yield* walk(v);
    }
  }
}

/** The first text in a header: "Today", "Yesterday", "Monday", "Oct 25". */
function headerText(header: unknown): string | null {
  for (const [k, v] of walk(header)) {
    if ((k === 'text' || k === 'simpleText' || k === 'content') && typeof v === 'string' && v.trim()) {
      return v.trim();
    }
  }
  return null;
}

/** The red bar's share of the video, 0..1, or null without one. */
function progress(video: unknown): number | null {
  for (const [k, v] of walk(video)) {
    if ((k === 'percentDurationWatched' || k === 'startPercent') && typeof v === 'number') {
      return Math.max(0, Math.min(1, v / 100));
    }
  }
  return null;
}

/** The video ids in a section, each with the object that describes it. */
function* videosIn(section: unknown): Generator<[string, unknown]> {
  for (const [k, v] of walk(section)) {
    if (!isNode(v)) continue;
    if (k === 'videoRenderer' && typeof v.videoId === 'string') yield [v.videoId, v];
    else if (k === 'lockupViewModel' && typeof v.contentId === 'string' &&
      (v.contentType === undefined || v.contentType === 'LOCKUP_CONTENT_TYPE_VIDEO')) yield [v.contentId, v];
    else if (k === 'reelWatchEndpoint' && typeof v.videoId === 'string') yield [v.videoId, v];
  }
}

/** Which day a section header names, in the page's language. */
export function dayOf(header: string | null, locale: string | null): 0 | 1 | null {
  if (!header) return null;
  const words = (offset: number) => {
    try {
      return new Intl.RelativeTimeFormat(locale ?? 'en', { numeric: 'auto' }).format(offset, 'day');
    } catch {
      return null;
    }
  };
  const text = header.toLocaleLowerCase();
  if (text === words(0)?.toLocaleLowerCase()) return 0;
  if (text === words(-1)?.toLocaleLowerCase()) return 1;
  return null;
}

export function parseHistoryPage(html: string): HistoryPage {
  const loggedIn = /"LOGGED_IN":\s*true/.test(html);
  const account = loggedIn ? config(html, 'DATASYNC_ID') : null;
  if (!account) return { account: null, items: [] };
  const locale = config(html, 'HL');

  const items = new Map<string, HistoryItem>();
  for (const [k, section] of walk(initialData(html))) {
    if (k !== 'itemSectionRenderer' || !isNode(section)) continue;
    const day = dayOf(headerText(section.header), locale);
    for (const [id, video] of videosIn(section.contents)) {
      // Newest first: a video watched twice keeps its latest day.
      if (!VIDEO_ID.test(id) || items.has(id)) continue;
      items.set(id, { video_id: id, share: progress(video), day });
    }
  }
  return { account, items: Array.from(items.values()).slice(0, MAX_ITEMS) };
}

export type HistoryState = 'ask' | 'on' | 'off';

/**
 * 'ask' shows the card on youtube.com, until answered and again for another
 * Google account; otherwise the popup has a line to turn it off, or on again.
 */
export function historyState(stored: Record<string, unknown>): HistoryState {
  const consented = Array.isArray(stored[HISTORY_CONSENT_KEY]) && (stored[HISTORY_CONSENT_KEY] as unknown[]).length > 0;
  if (stored[HISTORY_NEW_ACCOUNT_KEY]) return 'ask';
  if (consented) return 'on';
  return stored[HISTORY_DECLINED_KEY] ? 'off' : 'ask';
}

/** The consent text: exactly what happens, and nothing it doesn't do. */
export function consentText(languageName: string): string {
  return `The video ids on your YouTube history page are checked against Langfour's ${languageName} library, and only matches are kept.`;
}
