// "Yesterday on YouTube": the recap of the videos watched yesterday, on any
// device, in the extension popup and on the web Practice page
// (apps/web/src/app/vocabulary/YoutubeRecap.tsx imports this file). One
// line on what was watched, the new words in one comma-separated row, and
// one button that adds them all; tapping a word leaves it out. The API
// decides which words qualify (apps/api/watch.py).
//
// No DOM and no chrome.* here, so both apps can use it and it can be tested.

export type RecapWord = { word_id: number; word: string; video_id: string };
export type Recap = { day: string; videos: number; minutes: number; words: RecapWord[] };

function localDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Yesterday in the user's time zone: its date, and when it began and ended. */
export function yesterday(now: Date = new Date()): { day: string; start: string; end: string } {
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const start = new Date(end.getFullYear(), end.getMonth(), end.getDate() - 1);
  return { day: localDate(start), start: start.toISOString(), end: end.toISOString() };
}

export function recapPath(language: string, now: Date = new Date()): string {
  const { day, start, end } = yesterday(now);
  const q = new URLSearchParams({ language, day, start, end });
  return `/api/watch/recap?${q}`;
}

/** "3 videos · 41 min". */
export function recapStats(recap: Pick<Recap, 'videos' | 'minutes'>): string {
  const videos = recap.videos === 1 ? '1 video' : `${recap.videos} videos`;
  return recap.minutes > 0 ? `${videos} · ${recap.minutes} min` : videos;
}

export function addLabel(count: number): string {
  return `Add ${count} to reviews`;
}

/** What "Add" sends: the words not tapped away, each with its video. */
export function picks(recap: Recap, left: ReadonlySet<number>): { word_id: number; video_id: string }[] {
  return recap.words
    .filter((w) => !left.has(w.word_id))
    .map((w) => ({ word_id: w.word_id, video_id: w.video_id }));
}
