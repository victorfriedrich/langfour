// Fit badges on YouTube thumbnails (docs/plans/youtube-plan.md, feature 3):
// how much of a video the user would understand, before they click it.
//
// YouTube renders cards as you scroll and reuses them as you navigate, so an
// observer looks for cards (youtubeSelectors.ts) whenever the page changes
// and asks the background for the ones it hasn't seen, a batch at a time.
// The badge is one number, the share of the words spoken that the user
// knows; hovering it adds how many different words are new. A video the
// corpus doesn't have offers "+ Add" on hover, which queues it.
//
// Drawn in the thumbnail's bottom-left corner, styled like YouTube's own
// duration label in the bottom-right, which reads on any thumbnail in both
// themes. It stays clear of the red progress bar the same way that label does.
import type { Language } from './languages';
import { askBackground } from './messages';
import { FIT_BATCH, FIT_CACHE_KEY, QueueStatus, QueueVideoResponse, StoredFits, VideoFit, VideoFitResponse } from './videoFit';
import { findVideoCards, OBSERVED_ATTRIBUTES, VIDEO_CARD, VideoCard } from './youtubeSelectors';

const BADGE = 'langfour-fit';
const SCAN_DELAY_MS = 300;
// After a failed request (signed out, API down), wait before asking again.
const RETRY_AFTER_MS = 60_000;

const CSS = `
.${BADGE} {
  position: absolute; left: 8px; bottom: 8px; z-index: 2;
  display: flex; gap: 4px; padding: 1px 4px; border: 0; border-radius: 4px;
  background: rgba(0, 0, 0, 0.6); color: #fff;
  font: 500 12px/18px Roboto, Arial, sans-serif; white-space: nowrap;
}
.${BADGE}-more { display: none; }
.${BADGE}:hover .${BADGE}-more { display: inline; }
.${BADGE}-add { display: none; cursor: pointer; background: #4f46e5; }
.${BADGE}-add:disabled { cursor: default; background: rgba(0, 0, 0, 0.6); }
:is(${VIDEO_CARD}):hover .${BADGE}-add { display: block; }
`;

export function percentLabel(percentUnderstood: number): string {
  // Floor: 99.6% heard is not everything heard.
  return `${Math.floor(percentUnderstood)}%`;
}

export function queuedLabel(status: QueueStatus): string {
  return status === 'failed' || status === 'skipped' ? 'Unavailable' : 'Queued';
}

/** What a badge shows, so a card is only redrawn when that changes. */
function stateOf(fit: VideoFit): string {
  if (fit.status === 'scored') return `${fit.percentUnderstood}/${fit.newWords}`;
  if (fit.status === 'unindexed') return `add/${fit.queued ?? ''}`;
  return 'hidden';
}

export type FitBadges = { rescan: () => void; stop: () => void };

export function startFitBadges(getLanguage: () => Language | null): FitBadges {
  const fits = new Map<string, VideoFit>();
  const asking = new Set<string>();
  let language: Language | null = null;
  let retryAt = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const style = document.createElement('style');
  style.textContent = CSS;
  (document.head ?? document.documentElement).appendChild(style);

  const badgeIn = (box: HTMLElement) => box.querySelector<HTMLElement>(`:scope > .${BADGE}`);

  function removeBadges(): void {
    document.querySelectorAll(`.${BADGE}`).forEach((el) => el.remove());
  }

  function render({ videoId, box }: VideoCard, fit: VideoFit): void {
    const state = stateOf(fit);
    const current = badgeIn(box);
    if (current?.dataset.videoId === videoId && current.dataset.state === state) return;
    current?.remove();
    if (fit.status === 'hidden') return;

    let badge: HTMLElement;
    if (fit.status === 'scored') {
      badge = document.createElement('div');
      const percent = document.createElement('span');
      percent.textContent = percentLabel(fit.percentUnderstood);
      const more = document.createElement('span');
      more.className = `${BADGE}-more`;
      more.textContent = `· ${fit.newWords} new`;
      badge.append(percent, more);
    } else {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `${BADGE}-add`;
      button.textContent = fit.queued ? queuedLabel(fit.queued) : '+ Add';
      button.disabled = Boolean(fit.queued);
      // Inside the thumbnail's link: a click must not open the video.
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (!button.disabled) add(videoId, button);
      });
      badge = button;
    }
    badge.classList.add(BADGE);
    badge.dataset.videoId = videoId;
    badge.dataset.state = state;
    box.appendChild(badge);
  }

  async function add(videoId: string, button: HTMLButtonElement): Promise<void> {
    if (!language) return;
    button.disabled = true;
    const response = await askBackground<QueueVideoResponse>(
      { type: 'QUEUE_VIDEO', language, videoId },
      { attempts: 1 },
    );
    if (!response?.ok) {
      button.disabled = false;
      return;
    }
    fits.set(videoId, { status: 'unindexed', queued: response.status });
    scan();
  }

  async function ask(ids: string[], lang: Language): Promise<void> {
    ids.forEach((id) => asking.add(id));
    try {
      const response = await askBackground<VideoFitResponse>(
        { type: 'VIDEO_FIT', language: lang, videoIds: ids },
        { attempts: 1, timeoutMs: 20_000 },
      );
      if (!response?.ok) {
        retryAt = Date.now() + RETRY_AFTER_MS;
        return;
      }
      if (lang !== language) return;
      for (const [id, fit] of Object.entries(response.videos)) fits.set(id, fit);
    } finally {
      ids.forEach((id) => asking.delete(id));
    }
    scan();
  }

  function scan(): void {
    timer = undefined;
    const lang = getLanguage();
    if (lang !== language) {
      language = lang;
      fits.clear();
      removeBadges();
    }
    if (!lang) return;

    const toAsk: string[] = [];
    for (const card of findVideoCards(document)) {
      const fit = fits.get(card.videoId);
      if (fit) {
        render(card, fit);
        continue;
      }
      // A reused card still showing the video it had before.
      const stale = badgeIn(card.box);
      if (stale && stale.dataset.videoId !== card.videoId) stale.remove();
      if (!asking.has(card.videoId)) toAsk.push(card.videoId);
    }

    const ids = [...new Set(toAsk)];
    if (!ids.length || Date.now() < retryAt) return;
    for (let i = 0; i < ids.length; i += FIT_BATCH) void ask(ids.slice(i, i + FIT_BATCH), lang);
  }

  function scheduleScan(): void {
    if (timer === undefined) timer = setTimeout(scan, SCAN_DELAY_MS);
  }

  // The player rewrites its own controls many times a second; only changes
  // elsewhere can add or reuse cards.
  const outsidePlayer = (record: MutationRecord) => {
    const target = record.target instanceof Element ? record.target : record.target.parentElement;
    return !target?.closest(`#movie_player, .${BADGE}`);
  };
  const observer = new MutationObserver((records) => {
    if (records.some(outsidePlayer)) scheduleScan();
  });
  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: OBSERVED_ATTRIBUTES,
  });

  // The background cleared its cache: the user's words changed, so every
  // number on the page did too.
  const onStorageChange = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
    const change = changes[FIT_CACHE_KEY];
    if (area !== 'local' || !change) return;
    const before = (change.oldValue as StoredFits | undefined)?.clearedAt;
    const after = (change.newValue as StoredFits | undefined)?.clearedAt;
    if (before === after) return;
    fits.clear();
    retryAt = 0;
    removeBadges();
    scheduleScan();
  };
  chrome.storage.onChanged.addListener(onStorageChange);

  scheduleScan();
  return {
    rescan: () => {
      retryAt = 0;
      scheduleScan();
    },
    stop: () => {
      observer.disconnect();
      chrome.storage.onChanged.removeListener(onStorageChange);
      clearTimeout(timer);
      removeBadges();
      style.remove();
    },
  };
}
