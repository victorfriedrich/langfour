// Where a word saved from the page in a tab came from, for its 'saved' word
// event. Only a YouTube watch page names one: the web Videos page counts the
// words saved from a video when the learner comes back from it
// (apps/api/home.py, came_back), by this context's media.

export type SavedContext = { site: 'youtube'; media: string };

const YOUTUBE_HOSTS = new Set(['www.youtube.com', 'm.youtube.com', 'youtube.com']);

export function savedContext(tabUrl: string | undefined): SavedContext | null {
  if (!tabUrl) return null;
  let url: URL;
  try {
    url = new URL(tabUrl);
  } catch {
    return null;
  }
  if (url.protocol !== 'https:' || !YOUTUBE_HOSTS.has(url.hostname) || url.pathname !== '/watch') return null;
  const id = url.searchParams.get('v');
  return id && /^[A-Za-z0-9_-]{11}$/.test(id) ? { site: 'youtube', media: `youtube:${id}` } : null;
}
