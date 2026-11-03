// Every YouTube selector the fit badges (youtubeFit.ts) and the full-title
// box (youtubeTitles.ts) rely on. YouTube's
// markup changes often, so they live here and nowhere else, and
// youtubeSelectors.test.ts runs them against pages saved in test/youtube/,
// and youtubeSelectors.live.test.ts against youtube.com itself, daily in CI.
// When a badge stops showing, recapture those pages (test/youtube/README.md)
// and fix what the tests then report.

// Video cards on Home, channel pages (ytd-rich-item-renderer holding a
// yt-lockup-view-model), Search (ytd-video-renderer) and the watch page's
// sidebar (yt-lockup-view-model). The older sidebar and channel-grid cards
// are kept while YouTube still serves them to some accounts. Anything else
// with a thumbnail (playlist panels, the miniplayer, end screens) is left
// alone.
export const VIDEO_CARD = [
  'ytd-rich-item-renderer',
  'ytd-video-renderer',
  'yt-lockup-view-model',
  'ytd-compact-video-renderer',
  'ytd-grid-video-renderer',
].join(', ');

// The link around a card's thumbnail: lockups, then the older ytd-thumbnail.
const THUMBNAIL_LINK = 'a.ytLockupViewModelContentImage, ytd-thumbnail a#thumbnail';

// The positioned box the thumbnail is drawn in, which the badge is placed in.
const THUMBNAIL_BOX = 'yt-thumbnail-view-model, ytd-thumbnail';

// The duration label in the thumbnail's bottom-right corner.
const DURATION_TEXT = '.ytBadgeShapeText, ytd-thumbnail-overlay-time-status-renderer #text';
const DURATION = /^\d{1,2}(:\d{2}){1,2}$/;

export type VideoCard = {
  videoId: string;
  /** Hovering it reveals "+ Add". */
  card: HTMLElement;
  /** The thumbnail box the badge goes in. */
  box: HTMLElement;
};

/** The id of a /watch?v= link. Shorts (/shorts/<id>) and anything else: null. */
export function videoIdFromHref(href: string | null): string | null {
  if (!href) return null;
  let url: URL;
  try {
    url = new URL(href, 'https://www.youtube.com');
  } catch {
    return null;
  }
  if (url.pathname !== '/watch') return null;
  const id = url.searchParams.get('v');
  return id && /^[A-Za-z0-9_-]{11}$/.test(id) ? id : null;
}

/**
 * Only a video with a running time gets a badge. Live streams, premieres and
 * playlists or mixes show "LIVE", nothing, or a video count in that corner,
 * in whatever language YouTube is set to, so a missing time is what they
 * have in common. Overlays render after the card, so a card without one is
 * looked at again on the next scan rather than given up on.
 */
function hasDuration(link: Element): boolean {
  return Array.from(link.querySelectorAll(DURATION_TEXT)).some((el) =>
    DURATION.test(el.textContent?.trim() ?? ''),
  );
}

/** The video cards under `root` that can take a badge now. */
export function findVideoCards(root: ParentNode): VideoCard[] {
  const cards: VideoCard[] = [];
  for (const link of Array.from(root.querySelectorAll<HTMLAnchorElement>(THUMBNAIL_LINK))) {
    const card = link.closest<HTMLElement>(VIDEO_CARD);
    if (!card) continue;
    const videoId = videoIdFromHref(link.getAttribute('href'));
    if (!videoId || !hasDuration(link)) continue;
    const box = link.querySelector<HTMLElement>(THUMBNAIL_BOX) ?? link.closest<HTMLElement>(THUMBNAIL_BOX);
    if (!box) continue;
    cards.push({ videoId, card, box });
  }
  return cards;
}

/** The card under the pointer, if it can take a badge. */
export function cardAt(target: Element): VideoCard | null {
  const card = target.closest<HTMLElement>(VIDEO_CARD);
  if (!card) return null;
  return findVideoCards(card).find((found) => found.card === card) ?? null;
}

// A card's title link: lockups, then the older cards.
const VIDEO_TITLE = 'a.ytLockupMetadataViewModelTitle, #video-title';

/** The title of a video card under the pointer. */
export function titleAt(target: Element): HTMLElement | null {
  const title = target.closest<HTMLElement>(VIDEO_TITLE);
  return title?.closest(VIDEO_CARD) ? title : null;
}

// The inline preview that starts playing over a hovered thumbnail. It is
// drawn outside the card, over it, so the pointer is still on that card.
export const INLINE_PREVIEW = 'ytd-video-preview';

// What youtubeFit.ts watches for: attribute changes on these links mean
// YouTube reused a card for another video.
export const OBSERVED_ATTRIBUTES = ['href'];
