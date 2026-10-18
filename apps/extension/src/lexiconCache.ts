// The background's copies of the dictionary and the user's word statuses,
// so classifying an article (lexicon.ts) needs no request in the common
// case. Both are used as they are and refreshed after the answer, so a cold
// database never sits between opening an article and seeing its marks.
//
// The dictionary goes to IndexedDB: ~3 MB per language, too much for
// chrome.storage.local's quota. Nothing says when it changed (words and
// wordforms have no timestamps), so it is fetched again once it is a week
// old. Statuses are small and change whenever the user saves or reviews a
// word, so they are refreshed on every use.
import { debugLog } from './config';
import { Lexicon, parseLexicon } from './lexicon';
import type { WordStatus } from './messages';
import { ensureSupabaseSession, supabase } from './supabaseclient';

const LEXICON_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
// Words per lexicon_page call: ~1 MB and 0.3-2 s cold, well inside the
// authenticated role's 8 s statement timeout.
const LEXICON_PAGE_WORDS = 10000;
// Bump when the stored shape or lexicon_page's format changes.
const LEXICON_FORMAT = 1;

const DB_NAME = 'langfour';
const LEXICON_STORE = 'lexicons';
const STATUSES_KEY = 'wordStatuses';

type StoredLexicon = { language: string; format: number; savedAt: number; pages: string[] };
type StoredStatuses = { userId: string; savedAt: number; entries: [number, WordStatus][] };

// ---------------------------------------------------------------- IndexedDB

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore(LEXICON_STORE, { keyPath: 'language' });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function readStoredLexicon(language: string): Promise<StoredLexicon | undefined> {
  const db = await openDb();
  try {
    return await new Promise((resolve, reject) => {
      const request = db.transaction(LEXICON_STORE).objectStore(LEXICON_STORE).get(language);
      request.onsuccess = () => resolve(request.result as StoredLexicon | undefined);
      request.onerror = () => reject(request.error);
    });
  } finally {
    db.close();
  }
}

async function writeStoredLexicon(lexicon: StoredLexicon): Promise<void> {
  const db = await openDb();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(LEXICON_STORE, 'readwrite');
      tx.objectStore(LEXICON_STORE).put(lexicon);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } finally {
    db.close();
  }
}

// ---------------------------------------------------------------- Dictionary

type LoadedLexicon = { lexicon: Lexicon; savedAt: number };

// Parsed copies for this worker's lifetime, and downloads under way, so
// several readers opening at once share one download.
const lexicons = new Map<string, LoadedLexicon>();
const downloads = new Map<string, Promise<LoadedLexicon>>();

async function downloadLexicon(language: string): Promise<LoadedLexicon> {
  const { supabaseSession } = await chrome.storage.local.get('supabaseSession');
  if (!(await ensureSupabaseSession(supabaseSession))) throw new Error('No Supabase session available');

  const started = Date.now();
  const pages: string[] = [];
  let after = 0;
  for (;;) {
    const { data, error } = await supabase.rpc('lexicon_page', {
      language_filter: language,
      after_word_id: after,
      page_words: LEXICON_PAGE_WORDS,
    });
    if (error) throw new Error(`lexicon_page failed: ${error.message}`);
    const page = ((data ?? []) as { last_word_id: number | null; entries: string | null }[])[0];
    if (!page?.last_word_id || !page.entries) break;
    pages.push(page.entries);
    after = page.last_word_id;
  }
  if (!pages.length) throw new Error(`No dictionary for ${language}`);

  const stored: StoredLexicon = { language, format: LEXICON_FORMAT, savedAt: Date.now(), pages };
  await writeStoredLexicon(stored).catch((error: unknown) => console.warn('Could not store the dictionary:', error));
  const loaded = { lexicon: parseLexicon(pages), savedAt: stored.savedAt };
  lexicons.set(language, loaded);
  debugLog(`Downloaded the ${language} dictionary in ${Date.now() - started} ms`);
  return loaded;
}

function startDownload(language: string): Promise<LoadedLexicon> {
  let download = downloads.get(language);
  if (!download) {
    download = downloadLexicon(language).finally(() => downloads.delete(language));
    downloads.set(language, download);
  }
  return download;
}

/** The dictionary of a language: in memory, else stored, else downloaded. */
export async function getLexicon(language: string): Promise<Lexicon> {
  let loaded = lexicons.get(language);
  if (!loaded) {
    const stored = await readStoredLexicon(language).catch((error: unknown) => {
      console.warn('Could not read the stored dictionary:', error);
      return undefined;
    });
    if (stored?.format === LEXICON_FORMAT && stored.pages.length) {
      loaded = { lexicon: parseLexicon(stored.pages), savedAt: stored.savedAt };
      lexicons.set(language, loaded);
    }
  }
  if (!loaded) return (await startDownload(language)).lexicon;

  // A week-old copy still answers now; the next article gets the new one.
  if (Date.now() - loaded.savedAt > LEXICON_MAX_AGE_MS) {
    startDownload(language).catch((error: unknown) => console.warn('Could not refresh the dictionary:', error));
  }
  return loaded.lexicon;
}

// ---------------------------------------------------------------- Statuses

let statuses: { userId: string; byWord: Map<number, WordStatus> } | null = null;
let statusRefresh: Promise<Map<number, WordStatus>> | null = null;

async function fetchStatuses(userId: string): Promise<Map<number, WordStatus>> {
  const { supabaseSession } = await chrome.storage.local.get('supabaseSession');
  if (!(await ensureSupabaseSession(supabaseSession))) throw new Error('No Supabase session available');
  const { data, error } = await supabase.rpc('my_word_statuses');
  if (error) throw new Error(`my_word_statuses failed: ${error.message}`);

  const entries = (data ?? []) as [number, WordStatus][];
  const byWord = new Map(entries);
  // Signed out or switched account meanwhile: keep nothing of this user.
  const { supabaseSession: current } = await chrome.storage.local.get('supabaseSession');
  if (current?.user?.id === userId) {
    statuses = { userId, byWord };
    const stored: StoredStatuses = { userId, savedAt: Date.now(), entries };
    await chrome.storage.local.set({ [STATUSES_KEY]: stored });
  }
  return byWord;
}

function refreshStatuses(userId: string): Promise<Map<number, WordStatus>> {
  statusRefresh ??= fetchStatuses(userId).finally(() => { statusRefresh = null; });
  return statusRefresh;
}

/**
 * The user's statuses by word id. A saved copy answers at once and is
 * refreshed behind it, so a review or sync elsewhere shows from the next
 * article on; only the very first use waits for the request.
 */
export async function getStatuses(userId: string): Promise<ReadonlyMap<number, WordStatus>> {
  if (statuses?.userId !== userId) {
    const { [STATUSES_KEY]: stored } = await chrome.storage.local.get(STATUSES_KEY);
    const saved = stored as StoredStatuses | undefined;
    statuses = saved?.userId === userId ? { userId, byWord: new Map(saved.entries) } : null;
  }
  if (!statuses) return refreshStatuses(userId);

  refreshStatuses(userId).catch((error: unknown) => console.warn('Could not refresh word statuses:', error));
  return statuses.byWord;
}

/** A word the user just saved is being learned, before the next refresh says so. */
export async function markLearning(wordId: number): Promise<void> {
  if (!statuses || statuses.byWord.get(wordId) === 'learning') return;
  statuses.byWord.set(wordId, 'learning');
  const stored: StoredStatuses = { userId: statuses.userId, savedAt: Date.now(), entries: [...statuses.byWord] };
  await chrome.storage.local.set({ [STATUSES_KEY]: stored });
}

/** Signing out drops the user's statuses; the dictionary is not theirs. */
export async function clearStatuses(): Promise<void> {
  statuses = null;
  await chrome.storage.local.remove(STATUSES_KEY);
}
