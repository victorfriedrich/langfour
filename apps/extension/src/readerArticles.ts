// Articles handed from the background to the reader page.
//
// Each extraction gets its own storage key and the reader page reads it from
// `?id=` in its URL. A single shared `currentArticle` key meant a second
// article overwrote the first, so going Back/Forward to an earlier reader tab
// (the normal way to leave the reader on iOS, where it replaces the page)
// showed the wrong article.
import type { ArticleData } from './messages';

export type StoredArticle = ArticleData & {
  /** Page the article came from, for the "original" link. */
  url?: string | null;
  siteName?: string | null;
  byline?: string | null;
  /** Set when extraction failed; `content` then holds the reason. */
  error?: boolean;
  savedAt: number;
};

const INDEX_KEY = 'readerArticleIds';
const PREFIX = 'readerArticle:';
/** Enough for Back/Forward across recent articles without growing storage forever. */
const KEEP = 15;

export async function storeArticle(article: Omit<StoredArticle, 'savedAt'>): Promise<string> {
  const id = crypto.randomUUID();
  const { [INDEX_KEY]: stored } = await chrome.storage.local.get(INDEX_KEY);
  const ids: string[] = Array.isArray(stored) ? stored : [];
  const kept = [id, ...ids].slice(0, KEEP);
  const dropped = ids.filter((old) => !kept.includes(old));

  await chrome.storage.local.set({
    [PREFIX + id]: { ...article, savedAt: Date.now() },
    [INDEX_KEY]: kept,
  });
  if (dropped.length) await chrome.storage.local.remove(dropped.map((old) => PREFIX + old));
  return id;
}

/** Falls back to the legacy single key for reader tabs opened by older builds. */
export async function loadArticle(id: string | null): Promise<StoredArticle | null> {
  if (id) {
    const key = PREFIX + id;
    const { [key]: article } = await chrome.storage.local.get(key);
    if (article) return article as StoredArticle;
  }
  const { currentArticle } = await chrome.storage.local.get('currentArticle');
  return currentArticle ? { ...currentArticle, savedAt: 0 } : null;
}

export function readerPageUrl(id: string): string {
  return chrome.runtime.getURL(`src/reader.html?id=${encodeURIComponent(id)}`);
}
