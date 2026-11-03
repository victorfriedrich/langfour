// The whole title of a video card, for the ones YouTube cuts off after two or
// three lines. Holding the pointer on such a title for a second lays a white
// box over it with every line, in the title's own font, as if the title had
// the room. YouTube's own tooltip (the title attribute) is held back while
// the pointer is there, so the two don't stack.
//
// The box ignores the pointer, so clicking still opens the video.
import { titleAt } from './youtubeSelectors';

const BOX = 'langfour-title';
const DELAY_MS = 1000;
// The box's padding, so its text lands on the title's own lines.
const PAD_X = 8;
const PAD_Y = 6;
const EDGE = 8;

const CSS = `
.${BOX} {
  position: fixed; z-index: 2020; box-sizing: border-box;
  padding: ${PAD_Y}px ${PAD_X}px; border-radius: 8px;
  background: #fff; color: #0f0f0f; box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
  pointer-events: none; white-space: normal; overflow-wrap: break-word;
}
`;

type Rect = { top: number; right: number; bottom: number; left: number };

/**
 * The part of `title` that is drawn: its own box, cut by every element up to
 * the card that clips what overflows it (the line clamp may sit on the link
 * or on the text inside it).
 */
function shownRect(title: HTMLElement, text: Node): Rect {
  const { top, right, bottom, left } = title.getBoundingClientRect();
  const shown = { top, right, bottom, left };
  const outside = (title.closest('h3') ?? title).parentElement;
  for (let el = text.parentElement; el && el !== outside; el = el.parentElement) {
    if (getComputedStyle(el).overflow === 'visible') continue;
    const r = el.getBoundingClientRect();
    shown.top = Math.max(shown.top, r.top);
    shown.right = Math.min(shown.right, r.right);
    shown.bottom = Math.min(shown.bottom, r.bottom);
    shown.left = Math.max(shown.left, r.left);
  }
  return shown;
}

/** Where the title is drawn, if some of its text is clipped. */
function cutOff(title: HTMLElement): { shown: Rect; font: CSSStyleDeclaration } | null {
  const range = document.createRange();
  range.selectNodeContents(title);
  const lines = Array.from(range.getClientRects()).filter((r) => r.width && r.height);
  const text = document.createTreeWalker(title, NodeFilter.SHOW_TEXT).nextNode();
  if (!lines.length || !text?.parentElement) return null;
  const shown = shownRect(title, text);
  const clipped = lines.some((r) => r.bottom > shown.bottom + 1 || r.right > shown.right + 1);
  return clipped ? { shown, font: getComputedStyle(text.parentElement) } : null;
}

export function startTitleBoxes(): void {
  let hovered: HTMLElement | null = null;
  // The element whose title attribute is held back, and that attribute.
  let muted: { el: Element; title: string } | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const style = document.createElement('style');
  style.textContent = CSS;
  (document.head ?? document.documentElement).appendChild(style);
  const box = document.createElement('div');
  box.className = BOX;
  box.hidden = true;
  document.body.appendChild(box);

  function leave(): void {
    clearTimeout(timer);
    hovered = null;
    box.hidden = true;
    if (muted && !muted.el.hasAttribute('title')) muted.el.setAttribute('title', muted.title);
    muted = null;
  }

  function show(title: HTMLElement): void {
    const found = cutOff(title);
    if (!found || hovered !== title) return;
    const { shown, font } = found;
    box.textContent = muted?.title || title.textContent?.replace(/\s+/g, ' ').trim() || '';
    box.style.font = font.font;
    box.style.letterSpacing = font.letterSpacing;
    const width = shown.right - shown.left + 2 * PAD_X;
    box.style.width = `${width}px`;
    box.style.left = `${Math.max(EDGE, Math.min(shown.left - PAD_X, innerWidth - EDGE - width))}px`;
    box.style.top = `${shown.top - PAD_Y}px`;
    box.hidden = false;
  }

  function enter(title: HTMLElement): void {
    hovered = title;
    if (!cutOff(title)) return;
    const named = title.closest('[title]');
    const text = named?.getAttribute('title');
    if (named && text && title.closest('h3')?.contains(named)) {
      muted = { el: named, title: text };
      named.removeAttribute('title');
    }
    timer = setTimeout(() => show(title), DELAY_MS);
  }

  function onPointerOver(event: MouseEvent): void {
    const target = event.target instanceof Element ? event.target : null;
    const title = target && titleAt(target);
    if (title === hovered) return;
    leave();
    if (title) enter(title);
  }

  // The box is placed once per hover; scrolling, clicking or leaving the page ends it.
  document.addEventListener('mouseover', onPointerOver, true);
  window.addEventListener('scroll', leave, { capture: true, passive: true });
  document.documentElement.addEventListener('mouseleave', leave);
  document.addEventListener('click', leave, true);
}
