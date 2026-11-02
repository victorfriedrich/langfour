// Fit badges on YouTube thumbnails (docs/plans/youtube-plan.md, feature 3):
// how much of a video the user would understand, before they click it.
//
// YouTube renders cards as you scroll and reuses them as you navigate, so an
// observer looks for cards (youtubeSelectors.ts) whenever the page changes
// and asks the background for the ones it hasn't seen, a batch at a time.
// The badge is one number, the share of the words spoken that the user
// knows; hovering it adds how many different words are new. A video the
// corpus doesn't have offers "+ Add" on hover, which queues it, unless YouTube
// says it is in another language: then hovering shows nothing.
//
// Drawn in the thumbnail's bottom-left corner, styled like YouTube's own
// duration label in the bottom-right, which reads on any thumbnail in both
// themes. It stays clear of the red progress bar the same way that label does.
//
// Hovering a card starts YouTube's inline preview, drawn outside the card and
// over its thumbnail, so nothing inside the thumbnail can be pointed at once
// it plays. What hovering shows (the new words, "+ Add") is therefore drawn in
// one fixed layer above the page, placed over the hovered card's badge.
import { LANGUAGES, type Language } from './languages';
import { askBackground } from './messages';
import { FIT_BATCH, FIT_CACHE_KEY, QueueStatus, QueueVideoResponse, StoredFits, VideoFit, VideoFitResponse } from './videoFit';
import { cardAt, findVideoCards, INLINE_PREVIEW, OBSERVED_ATTRIBUTES, VideoCard } from './youtubeSelectors';

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
.${BADGE}-layer { position: fixed; z-index: 2019; transform: translateY(-100%); }
.${BADGE}-layer:empty { display: none; }
.${BADGE}-layer > .${BADGE} { position: static; }
.${BADGE}-more { display: none; }
.${BADGE}:hover .${BADGE}-more { display: inline; }
.${BADGE}-add { cursor: pointer; background: #4f46e5; }
.${BADGE}-add:disabled { cursor: default; background: rgba(0, 0, 0, 0.6); }
`;

export function percentLabel(percentUnderstood: number): string {
  // Floor: 99.6% heard is not everything heard.
  return `${Math.floor(percentUnderstood)}%`;
}

export function queuedLabel(status: QueueStatus, language: Language): string {
  if (status === 'other_language') return `Not ${LANGUAGES[language].name}`;
  return status === 'failed' || status === 'skipped' ? 'Unavailable' : 'Queued';
}

/** What a badge shows, so a card is only redrawn when that changes. */
function stateOf(fit: VideoFit): string {
  if (fit.status === 'scored') return `${fit.percentUnderstood}/${fit.newWords}`;
  if (fit.status === 'unindexed') return `add/${fit.queued ?? ''}`;
  return fit.status;
}

function badgeElement(text: string): HTMLElement {
  const badge = document.createElement('div');
  badge.className = BADGE;
  const percent = document.createElement('span');
  percent.textContent = text;
  badge.append(percent);
  return badge;
}

export type FitBadges = { rescan: () => void; stop: () => void };

export function startFitBadges(getLanguage: () => Language | null): FitBadges {
  const fits = new Map<string, VideoFit>();
  const asking = new Set<string>();
  let language: Language | null = null;
  let retryAt = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let hovered: VideoCard | null = null;

  const style = document.createElement('style');
  style.textContent = CSS;
  (document.head ?? document.documentElement).appendChild(style);
  const layer = document.createElement('div');
  layer.className = `${BADGE}-layer`;
  document.body.appendChild(layer);

  const badgeIn = (box: HTMLElement) => box.querySelector<HTMLElement>(`:scope > .${BADGE}`);

  function removeBadges(): void {
    document.querySelectorAll(`.${BADGE}`).forEach((el) => el.remove());
    hideHover();
  }

  /** The thumbnail's own badge: the percentage, for scored videos only. */
  function render({ videoId, box }: VideoCard, fit: VideoFit): void {
    const state = stateOf(fit);
    const current = badgeIn(box);
    if (current?.dataset.videoId === videoId && current.dataset.state === state) return;
    current?.remove();
    if (fit.status !== 'scored') return;
    const badge = badgeElement(percentLabel(fit.percentUnderstood));
    badge.dataset.videoId = videoId;
    badge.dataset.state = state;
    box.appendChild(badge);
  }

  /** What the hover layer shows for a video: the badge with its new words, or "+ Add". */
  function hoverElement(videoId: string, fit: VideoFit): HTMLElement | null {
    if (fit.status === 'scored') {
      const badge = badgeElement(percentLabel(fit.percentUnderstood));
      const more = document.createElement('span');
      more.className = `${BADGE}-more`;
      more.textContent = `· ${fit.newWords} new`;
      badge.append(more);
      return badge;
    }
    if (fit.status !== 'unindexed' || !language) return null;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `${BADGE} ${BADGE}-add`;
    button.textContent = fit.queued ? queuedLabel(fit.queued, language) : '+ Add';
    button.disabled = Boolean(fit.queued);
    button.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!button.disabled) void add(videoId, button);
    });
    return button;
  }

  function hideHover(): void {
    hovered = null;
    layer.replaceChildren();
    delete layer.dataset.key;
  }

  function showHover(card: VideoCard): void {
    const fit = fits.get(card.videoId);
    const key = fit && `${card.videoId}/${stateOf(fit)}`;
    if (!fit || layer.dataset.key !== key) {
      const element = fit && hoverElement(card.videoId, fit);
      if (!element) {
        hideHover();
        return;
      }
      layer.replaceChildren(element);
      layer.dataset.key = key;
    }
    hovered = card;
    const rect = card.box.getBoundingClientRect();
    layer.style.left = `${rect.left + 8}px`;
    layer.style.top = `${rect.bottom - 8}px`;
  }

  function onPointerOver(event: MouseEvent): void {
    const target = event.target instanceof Element ? event.target : null;
    // On the layer itself, or on the preview playing over the hovered card.
    if (!target || layer.contains(target) || (hovered && target.closest(INLINE_PREVIEW))) return;
    const card = cardAt(target);
    if (card) showHover(card);
    else hideHover();
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
    if (hovered?.videoId === videoId) showHover(hovered);
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
    if (hovered) showHover(hovered);
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
    return !target?.closest(`#movie_player, ${INLINE_PREVIEW}, .${BADGE}, .${BADGE}-layer`);
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

  // The layer is placed once per hover; scrolling or leaving the page ends it.
  document.addEventListener('mouseover', onPointerOver, true);
  window.addEventListener('scroll', hideHover, { capture: true, passive: true });
  document.documentElement.addEventListener('mouseleave', hideHover);

  scheduleScan();
  return {
    rescan: () => {
      retryAt = 0;
      scheduleScan();
    },
    stop: () => {
      observer.disconnect();
      chrome.storage.onChanged.removeListener(onStorageChange);
      document.removeEventListener('mouseover', onPointerOver, true);
      window.removeEventListener('scroll', hideHover, { capture: true });
      document.documentElement.removeEventListener('mouseleave', hideHover);
      clearTimeout(timer);
      removeBadges();
      layer.remove();
      style.remove();
    },
  };
}
