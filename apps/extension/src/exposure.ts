// Words the user read: caption lines shown while a video played, and reader
// paragraphs they stayed on long enough to read. Both end up in the
// background's recordExposure, which keeps the learning and new words and
// logs them through /api/exposure, once per word per video or page
// (docs/plans/learner-word-data-model.md: exposure counts only what the user
// chose to read or hear).
//
// The rules live here, free of the DOM, so they can be tested; index.ts and
// reader.ts feed them what is on screen.

const WORD = /[\p{L}\p{M}]+/gu;

/** How often what was read is sent, besides when the page is hidden or left. */
export const FLUSH_MS = 30_000;

// Captions are sampled this often; a word counts once it was on screen for
// CAPTION_TICKS samples in a row while the video played.
export const CAPTION_TICK_MS = 500;
export const CAPTION_TICKS = 2;
// Faster than this is skimming, not watching.
export const MAX_PLAYBACK_RATE = 1.5;

// A paragraph counts once it was on screen this long: its words at a fast
// reading pace, and never under a second.
const FAST_WORDS_PER_MINUTE = 400;
const MIN_READ_MS = 1000;

export function tokensOf(text: string): string[] {
  return text.match(WORD) ?? [];
}

/**
 * Where something was read, as the server groups exposures: one key per
 * YouTube video whichever URL shows it, otherwise the page without its query
 * or fragment.
 */
export function mediaKey(href: string): string {
  let url: URL;
  try {
    url = new URL(href);
  } catch {
    return href.slice(0, 500);
  }
  if (/(^|\.)youtube\.com$/.test(url.hostname)) {
    const id = url.searchParams.get('v') ?? url.pathname.match(/^\/(?:shorts|live)\/([^/?#]+)/)?.[1];
    if (id) return `youtube:${id}`;
  }
  return `${url.origin}${url.pathname}`.slice(0, 500);
}

export function msToRead(words: number): number {
  return Math.max(MIN_READ_MS, (words * 60_000) / FAST_WORDS_PER_MINUTE);
}

/**
 * Caption words on screen during playback. Counts by word rather than by
 * line, so YouTube's rolling auto-captions, which grow a line word by word,
 * count the same as whole lines.
 */
export class CaptionWords {
  private onScreen = new Map<string, number>();
  private counted = new Set<string>();

  /**
   * One sample of the words on screen while the video plays. Returns the
   * words that have now been there long enough, each once until reset().
   */
  sample(words: Iterable<string>): string[] {
    const next = new Map<string, number>();
    const done: string[] = [];
    for (const word of words) {
      if (next.has(word)) continue;
      const ticks = (this.onScreen.get(word) ?? 0) + 1;
      next.set(word, ticks);
      if (ticks >= CAPTION_TICKS && !this.counted.has(word)) {
        this.counted.add(word);
        done.push(word);
      }
    }
    this.onScreen = next;
    return done;
  }

  /** A sample with the video paused, seeking or hidden: words on screen start over. */
  interrupt(): void {
    this.onScreen.clear();
  }

  /** Another video: every word can count again. */
  reset(): void {
    this.onScreen.clear();
    this.counted.clear();
  }
}

/** Words waiting to be sent, per video or page. */
export class ExposureQueue {
  private pending = new Map<string, Set<string>>();

  add(media: string, words: Iterable<string>): void {
    let set = this.pending.get(media);
    if (!set) this.pending.set(media, (set = new Set()));
    for (const word of words) set.add(word);
  }

  /** Everything queued, emptied. */
  take(): { media: string; tokens: string[] }[] {
    const out = Array.from(this.pending, ([media, words]) => ({ media, tokens: Array.from(words) }))
      .filter((batch) => batch.tokens.length > 0);
    this.pending.clear();
    return out;
  }
}
