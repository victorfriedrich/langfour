/**
 * Daily words: each day, the learner's next words go straight into their
 * review queue. How many (the pace) and from which topics are chosen once,
 * in onboarding, and kept in the Supabase user's metadata:
 *
 *   user_metadata.daily_words = { es: { pace: 15, topics: ['Cooking'], last: '2026-11-09' } }
 *
 * `last` is the learner's local date of the last batch, so a day is theirs
 * and a second tab or device the same day adds nothing.
 */
import { supabase } from './supabaseclient';

export const PACES = [10, 15, 25] as const;
export const DEFAULT_PACE = 15;
export const DAILY_SOURCE = 'Daily words';

export interface DailyPrefs {
  pace: number;
  topics: string[];
  last?: string;
}

type AllPrefs = Record<string, DailyPrefs>;

/** The learner's calendar day, e.g. 2026-11-09. */
export function todayKey(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function dailyWordsQuery(language: string, prefs: DailyPrefs): string {
  const params = new URLSearchParams({ language, n: String(prefs.pace) });
  prefs.topics.forEach((t) => params.append('topics', t));
  return `/api/daily-words?${params}`;
}

/** Whether today's words are still to be added. */
export function isDue(prefs: DailyPrefs | undefined, today: string = todayKey()): prefs is DailyPrefs {
  return !!prefs && prefs.pace > 0 && prefs.last !== today;
}

async function readAll(): Promise<AllPrefs> {
  const { data } = await supabase.auth.getUser();
  return (data.user?.user_metadata?.daily_words as AllPrefs | undefined) ?? {};
}

export async function saveDailyPrefs(language: string, prefs: DailyPrefs): Promise<void> {
  const all = await readAll();
  const { error } = await supabase.auth.updateUser({ data: { daily_words: { ...all, [language]: prefs } } });
  if (error) throw error;
}

const running = new Map<string, Promise<number>>();

/**
 * Adds today's words if they are due. Returns how many were added. One run
 * per language at a time, so a page that renders twice adds them once.
 */
export function ensureDailyWords(
  language: string,
  fetchWithAuth: (url: string, options?: RequestInit) => Promise<Response>,
  addWords: (wordIds: number[], source: string) => Promise<unknown>,
): Promise<number> {
  const pending = running.get(language);
  if (pending) return pending;
  const run = (async () => {
    const all = await readAll();
    const prefs = all[language];
    const today = todayKey();
    if (!isDue(prefs, today)) return 0;
    const api = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    const res = await fetchWithAuth(`${api}${dailyWordsQuery(language, prefs)}`);
    if (!res.ok) throw new Error(`Daily words: ${res.status}`);
    const { word_ids: ids } = (await res.json()) as { word_ids: number[] };
    if (ids.length) await addWords(ids, DAILY_SOURCE);
    await supabase.auth.updateUser({ data: { daily_words: { ...all, [language]: { ...prefs, last: today } } } });
    return ids.length;
  })().finally(() => running.delete(language));
  running.set(language, run);
  return run;
}
