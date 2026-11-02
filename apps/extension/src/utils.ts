import { popupHeight, popupWidth } from './markup';
import debounce from 'lodash-es/debounce';
import { sanitizeHTML } from './sanitizeHTML';

export const logPrefix = 'Langfour ';

export function createElementFromHTML(htmlString: string) {
  const div = document.createElement('div');
  div.innerHTML = sanitizeHTML(htmlString.trim());
  return div.firstChild as HTMLElement;
}

export function isVisible(el?: HTMLElement | null) {
  if (!el) return false;

  const style = window.getComputedStyle(el);
  return (
    style.width !== '0' &&
    style.height !== '0' &&
    style.opacity !== '0' &&
    style.display !== 'none' &&
    style.visibility !== 'hidden'
  );
}

export function injectCss(path: string): void {
  const link = document.createElement('link');
  link.href = chrome.runtime.getURL(path);
  link.type = 'text/css';
  link.rel = 'stylesheet';
  document.getElementsByTagName('head')[0].appendChild(link);
}

export async function injectJs(path: string): Promise<void> {
  return new Promise<void>((resolve) => {
    const s = document.createElement('script');
    s.src = chrome.runtime.getURL(path);
    s.onload = function () {
      (this as HTMLScriptElement).remove();
      resolve();
    };
    (document.head || document.documentElement).appendChild(s);
  });
}

export function fetchTextNodes(node: Node | Text): Text[] {
  if (node instanceof Text) return [node];

  const result: Text[] = [];
  const walk = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, null);
  let textNode: Text | null = null;

  do {
    textNode = walk.nextNode() as Text;
    if (textNode) {
      result.push(textNode);
    }
  } while (textNode);

  return result;
}

export function positionElement(
  element: HTMLElement,
  anchorElement: HTMLElement,
  fitElement: HTMLElement,
) {
  const gap = 8;
  const anchorRect = anchorElement.getBoundingClientRect();
  const fitRect = fitElement.getBoundingClientRect();
  // The popup's real size: it changes once the translation arrives, and
  // index.ts repositions it every 100 ms. The constants only cover the first
  // frame, before it has rendered.
  const ownRect = element.getBoundingClientRect();
  const width = ownRect.width || popupWidth;
  const height = ownRect.height || popupHeight;
  // Sit above the whole caption box, not just the word, so no caption line
  // is covered; below it only when the player has no room above.
  const captionRect = (
    anchorElement.closest('.caption-window, .player-timedtext-text-container') ?? anchorElement
  ).getBoundingClientRect();

  // Only the part of the player on screen counts: the page can be scrolled
  // with the player partly out of view.
  const fitTop = Math.max(fitRect.top, 0);
  const fitBottom = Math.min(fitRect.bottom, window.innerHeight);
  const fitLeft = Math.max(fitRect.left, 0);
  const fitRight = Math.min(fitRect.right, window.innerWidth);

  let top = captionRect.top - height - gap;
  if (top < fitTop + gap) {
    const below = captionRect.bottom + gap;
    top = below + height <= fitBottom ? below : Math.max(fitTop + gap, anchorRect.top - height - gap);
  }
  const centre = anchorRect.left + anchorRect.width / 2;
  // In a player narrower than the popup, its start stays on screen.
  const left = Math.max(
    Math.min(centre - width / 2, fitRight - width - gap),
    fitLeft + gap,
  );

  element.style.left = `${left}px`;
  element.style.top = `${top}px`;
  // "position: fixed" is relative to a transformed ancestor when there is one
  // instead of the viewport, as with YouTube's mobile player at times: the
  // popup then landed lower, on top of the word. Correct by what actually
  // happened.
  const placedRect = element.getBoundingClientRect();
  element.style.left = `${2 * left - placedRect.left}px`;
  element.style.top = `${2 * top - placedRect.top}px`;
}

let stopScrollPosition: number | null = null;

window.addEventListener('scroll', (e: Event) => {
  if (stopScrollPosition !== null) {
    window.scrollTo(window.scrollX, stopScrollPosition);
    e.stopImmediatePropagation();
  }
});

export function disableScroll() {
  stopScrollPosition = window.scrollY;
}

export function enableScroll() {
  stopScrollPosition = null;
}

/**
 * Custom 'mouseenter' and 'mouseleave' addEventListener.
 * By means of document.elementsFromPoint this implementation works even when other element overlaps the target or when .
 * */
export default function addMouseEnterLeaveEventListeners({
  selector,
  ignoreElClassName,
  onEnter,
  onLeave,
}: {
  selector: string;
  ignoreElClassName: string;
  onEnter: (el: HTMLElement) => void;
  onLeave: (el: HTMLElement) => void;
}) {
  let selectedElement: HTMLElement | null = null;

  // Touch screens (Safari on iOS) have no hover: a tap on a word opens it, a
  // tap on the same word or anywhere else closes it. iOS also fakes mouse
  // events after a tap, so the hover path below stays off there.
  if (window.matchMedia('(hover: none)').matches) {
    const isOpen = () => document.querySelector(`.${ignoreElClassName}`) !== null;
    const wordAt = (x: number, y: number) =>
      (document.elementsFromPoint(x, y).find((e) => e.matches(selector)) as HTMLElement | undefined) ??
      null;
    // The words sit inside the video player, whose own touch handlers toggle
    // its controls and cancel the touch, so iOS often never sends a click.
    // Taps are therefore read from the touches themselves, at the window in
    // the capture phase, which runs before any of the page's handlers.
    let start: { x: number; y: number; time: number } | null = null;
    window.addEventListener(
      'touchstart',
      (event) => {
        const touch = event.touches.length === 1 ? event.touches[0] : null;
        start = touch ? { x: touch.clientX, y: touch.clientY, time: event.timeStamp } : null;
        if (touch && wordAt(touch.clientX, touch.clientY)) event.stopPropagation();
      },
      { capture: true },
    );
    window.addEventListener(
      'touchend',
      (event) => {
        const touch = event.changedTouches[0];
        const began = start;
        start = null;
        // Taps inside the popup (its + button) are the popup's own.
        if (!touch || !began || (event.target as Element | null)?.closest?.(`.${ignoreElClassName}`)) return;
        const isTap =
          Math.hypot(touch.clientX - began.x, touch.clientY - began.y) < 10 &&
          event.timeStamp - began.time < 500;
        if (!isTap) return;

        const word = wordAt(touch.clientX, touch.clientY);
        if (word) {
          // No click, no player controls: the tap belongs to the word.
          event.preventDefault();
          event.stopPropagation();
        }
        const reopen = word !== null && !(word === selectedElement && isOpen());
        if (selectedElement && isOpen()) onLeave(selectedElement);
        selectedElement = null;
        if (reopen && word) {
          onEnter(word);
          selectedElement = word;
        }
      },
      { capture: true, passive: false },
    );
    return;
  }

  // Leaving a word only counts once the pointer rests. On its way to the
  // popup's "+" it crosses the gap above the caption and often other words of
  // the caption, and acting on those closed or moved the popup under it.
  const settle = debounce((element: HTMLElement | undefined) => {
    if (selectedElement) onLeave(selectedElement);
    selectedElement = element ?? null;
    if (element) onEnter(element);
  }, 120);

  document.addEventListener(
    'mousemove',
    debounce(({ clientX, clientY }) => {
      const elementsUnderPointer = document.elementsFromPoint(clientX, clientY);
      const ignoreElement = elementsUnderPointer.find((e) =>
        e.classList.contains(ignoreElClassName),
      ) as HTMLElement;

      if (ignoreElement) {
        settle.cancel();
        return;
      }

      const element = elementsUnderPointer.find((e) => e.matches(selector)) as
        | HTMLElement
        | undefined;

      if (element === (selectedElement ?? undefined)) {
        settle.cancel();
      } else if (selectedElement) {
        settle(element);
      } else if (element) {
        onEnter(element);
        selectedElement = element;
      }
    }, 10),
  );
}
