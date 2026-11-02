// The background's side of the watch signal: desktop watches and unmarks on
// to the API, and the history page read every couple of hours while the
// browser is open, once the user said yes for the Google account signed in
// (watchHistory.ts). backgroundScript.ts routes the messages here.

import type { BackendRequest, BackendResponse } from './messages';
import { toLanguage } from './languages';
import {
  HISTORY_ALARM,
  HISTORY_CONSENT_KEY,
  HISTORY_DECLINED_ACCOUNTS_KEY,
  HISTORY_DECLINED_KEY,
  HISTORY_EVERY_MINUTES,
  HISTORY_LAST_READ_KEY,
  HISTORY_NEW_ACCOUNT_KEY,
  HISTORY_URL,
  parseHistoryPage,
} from './watchHistory';

type Backend = (request: BackendRequest) => Promise<BackendResponse>;

function json<T>(response: BackendResponse): T | null {
  if (!response.ok) return null;
  try {
    return JSON.parse(response.body) as T;
  } catch {
    return null;
  }
}

export async function watchStatus(backend: Backend, videoId: string, language: string) {
  const q = new URLSearchParams({ language });
  const response = await backend({ path: `/api/watch/${encodeURIComponent(videoId)}?${q}`, method: 'GET' });
  return json<{ indexed: boolean; watched: boolean }>(response);
}

export async function watchMark(backend: Backend, videoId: string, share: number, language: string) {
  const response = await backend({ path: '/api/watch', method: 'POST', body: { video_id: videoId, share, language } });
  return json<{ indexed: boolean; watched: boolean }>(response);
}

export async function watchUnmark(backend: Backend, videoId: string) {
  const response = await backend({ path: '/api/watch/unmark', method: 'POST', body: { video_id: videoId } });
  return json<{ indexed: boolean; watched: boolean }>(response);
}

export type HistoryReadResult = { kept?: number; error?: string };

/**
 * Reads the history page and sends its video ids on. Without consent for
 * the account signed in, nothing is sent: the page is dropped as soon as the
 * account is known, and the card asks. `consenting` is that yes, given for
 * whichever account is signed in now.
 */
export async function readHistory(backend: Backend, consenting = false): Promise<HistoryReadResult> {
  const stored = await chrome.storage.local.get([HISTORY_CONSENT_KEY, HISTORY_DECLINED_ACCOUNTS_KEY]);
  const consented: string[] = Array.isArray(stored[HISTORY_CONSENT_KEY]) ? stored[HISTORY_CONSENT_KEY] : [];
  if (!consenting && consented.length === 0) return { error: 'Not turned on' };
  const { preferredLanguage } = await chrome.storage.sync.get('preferredLanguage');
  const language = toLanguage(preferredLanguage);
  if (!language) return { error: 'No learning language' };

  let html: string;
  try {
    const response = await fetch(HISTORY_URL, { credentials: 'include' });
    if (!response.ok) return { error: `YouTube answered ${response.status}` };
    html = await response.text();
  } catch (error) {
    return { error: `Could not reach YouTube: ${String(error)}` };
  }
  const page = parseHistoryPage(html);
  if (!page.account) return { error: 'Not signed in to YouTube' };
  if (!consented.includes(page.account)) {
    if (!consenting) {
      const declined: unknown = stored[HISTORY_DECLINED_ACCOUNTS_KEY];
      if (!Array.isArray(declined) || !declined.includes(page.account)) {
        await chrome.storage.local.set({ [HISTORY_NEW_ACCOUNT_KEY]: page.account });
      }
      return { error: 'Another Google account is signed in' };
    }
    consented.push(page.account);
  }
  await chrome.storage.local.set({
    [HISTORY_CONSENT_KEY]: consented,
    [HISTORY_NEW_ACCOUNT_KEY]: false,
    [HISTORY_DECLINED_KEY]: false,
  });
  if (page.items.length === 0) return { kept: 0 };

  const response = await backend({ path: '/api/watch/history', method: 'POST', body: { language, items: page.items } });
  const kept = json<{ kept: number }>(response);
  if (!kept) return { error: response.statusText || `API answered ${response.status}` };
  await chrome.storage.local.set({ [HISTORY_LAST_READ_KEY]: Date.now() });
  return { kept: kept.kept };
}

/** Turning it off forgets every account's yes and deletes what it stored. */
export async function historyOff(backend: Backend): Promise<{ ok: boolean }> {
  await chrome.storage.local.set({
    [HISTORY_CONSENT_KEY]: [],
    [HISTORY_NEW_ACCOUNT_KEY]: false,
    [HISTORY_DECLINED_KEY]: true,
  });
  const response = await backend({ path: '/api/watch/history/off', method: 'POST' });
  return { ok: response.ok };
}

/** Every couple of hours while the browser runs, and at its start if due. */
export function scheduleHistoryReads(backend: Backend): void {
  // Safari on iOS may lack alarms; the history read is for desktop.
  if (!chrome.alarms) return;
  const readIfDue = async () => {
    const stored = await chrome.storage.local.get(HISTORY_LAST_READ_KEY);
    const last = Number(stored[HISTORY_LAST_READ_KEY]) || 0;
    if (Date.now() - last < (HISTORY_EVERY_MINUTES - 5) * 60_000) return;
    const result = await readHistory(backend);
    if (result.error) console.log('History not read:', result.error);
  };
  // The worker restarts often; re-creating the alarm each time would reset
  // it, and with a short delay, wake the worker every minute.
  chrome.alarms.get(HISTORY_ALARM, (existing) => {
    if (!existing) chrome.alarms.create(HISTORY_ALARM, { periodInMinutes: HISTORY_EVERY_MINUTES, delayInMinutes: 1 });
  });
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === HISTORY_ALARM) void readIfDue();
  });
}
