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

  let top = captionRect.top - height - gap;
  if (top < fitRect.top + gap) {
    const below = captionRect.bottom + gap;
    top = below + height <= fitRect.bottom ? below : Math.max(fitRect.top + gap, anchorRect.top - height - gap);
  }
  const centre = anchorRect.left + anchorRect.width / 2;
  const left = Math.min(
    Math.max(centre - width / 2, fitRect.left + gap),
    fitRect.right - width - gap,
  );

  element.style.left = `${left}px`;
  element.style.top = `${top}px`;
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

  document.addEventListener(
    'mousemove',
    debounce(({ clientX, clientY }) => {
      const elementsUnderPointer = document.elementsFromPoint(clientX, clientY);
      const ignoreElement = elementsUnderPointer.find((e) =>
        e.classList.contains(ignoreElClassName),
      ) as HTMLElement;

      if (ignoreElement) return;

      const element = elementsUnderPointer.find((e) => e.matches(selector)) as
        | HTMLElement
        | undefined;

      if (element && selectedElement !== element) {
        if (selectedElement) {
          onLeave(selectedElement);
        }
        onEnter(element);
        selectedElement = element;
      }
      if (!element && selectedElement) {
        onLeave(selectedElement);
        selectedElement = null;
      }
    }, 10),
  );
}
