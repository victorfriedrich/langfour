// chatgptHighlight.ts
//
// A Langfour button in chatgpt.com's header that marks ChatGPT's answers the
// way the reader marks an article: new words highlighted yellow, words being
// learned underlined, and a click on a word opens the reader's word popup. ChatGPT renders with React, so the words are painted
// with the CSS Custom Highlight API instead of being wrapped in spans: the
// page's DOM stays exactly as React left it, and streaming answers keep
// working while they are marked.

import { getPrefs } from './preferencePopup/prefs';
import { Language, LANGUAGES, toLanguage } from './languages';
import { readFileSync } from 'fs';
import { askBackground, ClassifiedWord, ClassifyWordsResponse, sendToBackground } from './messages';
import { SIGNED_OUT, translate } from './translate';
import { appendWordProgress, createLoadingPopup, createMessagePopup, createWordPopup } from './wordPopup';

// Parcel pastes the file in at build time; Vitest reads it from disk. (A
// bundle-text: import would do too, as long as no other content script
// imported the same file: Parcel can't build a shared inline bundle.)
const POPUP_CSS = readFileSync(__dirname + '/chatgptPopup.css', 'utf8');

const ENABLED_KEY = 'chatgptHighlightOn';
const NEW_HIGHLIGHT = 'langfour-new';
const LEARNING_HIGHLIGHT = 'langfour-learning';
// The word whose popup is open, like the reader's .word-active.
const ACTIVE_HIGHLIGHT = 'langfour-active';
// The conversation. ChatGPT renames its message markup now and then, so
// rather than chase it the whole area is read, minus what isn't an answer:
// the user's own prompts (often English, where "me" or "a" would be marked
// as Spanish), code, the composer, the header and the action buttons.
const CONVERSATION = 'main';
const USER_MESSAGE = '[data-message-author-role="user"], [data-content-search-unit-key$=":user"]';
const SKIP = `pre, code, button, textarea, form, header, nav, [contenteditable="true"], .sr-only, ${USER_MESSAGE}`;
// The header area holding "…" (Chat actions) and Share.
const HEADER_ACTIONS = 'header [data-testid="app-shell-header-context-menu-surface"]';
const STARTED_EVENT = 'langfour-chatgpt-started';
// The reader's split: runs of letters and combining marks are words.
const WORD = /[\p{L}\p{M}]+/gu;
// A streaming answer changes the page many times a second; re-marking at
// most this often keeps up without redoing the work for every token.
const REFRESH_MS = 500;

export type WordRange = { node: Text; start: number; end: number; token: string };

function inAnswer(node: Node): boolean {
  const parent = node.parentElement;
  return Boolean(parent?.closest(CONVERSATION) && !parent.closest(SKIP));
}

/** Every word of ChatGPT's answers, with where it sits. */
export function wordsIn(root: ParentNode): WordRange[] {
  const words: WordRange[] = [];
  for (const area of Array.from(root.querySelectorAll(CONVERSATION))) {
    const walker = document.createTreeWalker(area, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) => (inAnswer(node) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT),
    });
    let node: Node | null;
    while ((node = walker.nextNode())) {
      const text = node as Text;
      for (const match of text.data.matchAll(WORD)) {
        words.push({ node: text, start: match.index!, end: match.index! + match[0].length, token: match[0] });
      }
    }
  }
  return words;
}

// What the background said about each token; null when it is not
// vocabulary (names, acronyms, other languages). Cleared when the language,
// the account or the user's words may have changed.
const byToken = new Map<string, ClassifiedWord | null>();
let language: Language | null = null;
let enabled = false;
let refreshTimer: ReturnType<typeof setTimeout> | null = null;
let refreshing: Promise<void> | null = null;
let refreshAgain = false;
let buttonHost: HTMLElement | null = null;
let button: HTMLButtonElement | null = null;
// Holds the tooltip and the translation popup, above the whole page.
let overlay: HTMLElement | null = null;
// Logged once per switch-on, to tell "found no text" from "no new words".
let reported = false;

function supported(): boolean {
  return typeof Highlight === 'function' && 'highlights' in CSS;
}

// The registry is maplike; the tsconfig's libs ("dom" without
// "dom.iterable") leave its Map methods out of the types.
const highlights = () => CSS.highlights as unknown as Map<string, Highlight>;

function clearMarks(): void {
  highlights().delete(NEW_HIGHLIGHT);
  highlights().delete(LEARNING_HIGHLIGHT);
}

async function classify(tokens: string[], lang: Language): Promise<boolean> {
  if (!tokens.length) return true;
  const response = await askBackground<ClassifyWordsResponse>(
    { type: 'CLASSIFY_WORDS', language: lang, tokens },
    { timeoutMs: 20_000 },
  );
  if (!response?.ok) {
    console.warn('Langfour: could not classify words:', response ? response.error : 'no response');
    if (response?.error === 'No Supabase session available') setButton('signed-out');
    else setButton('failed');
    return false;
  }
  // A token the background left out is not vocabulary.
  for (const token of tokens) byToken.set(token, null);
  for (const word of response.words) byToken.set(word.token, word);
  return true;
}

async function markConversation(): Promise<void> {
  if (!enabled || !language) return;
  const words = wordsIn(document);
  const unseen = Array.from(new Set(words.map((w) => w.token).filter((token) => !byToken.has(token))));
  if (!(await classify(unseen, language)) || !enabled) return;
  if (!reported) {
    reported = true;
    console.info(`Langfour: ${words.length} words on the page, ${byToken.size} checked as ${LANGUAGES[language].name}`);
  }

  const newRanges: Range[] = [];
  const learningRanges: Range[] = [];
  for (const { node, start, end, token } of words) {
    const word = byToken.get(token);
    if (!word || (word.status !== 'new' && word.status !== 'learning')) continue;
    // The text may have changed while the background was answering.
    if (!node.isConnected || node.data.slice(start, end) !== token) continue;
    const range = new Range();
    range.setStart(node, start);
    range.setEnd(node, end);
    (word.status === 'new' ? newRanges : learningRanges).push(range);
  }
  highlights().set(NEW_HIGHLIGHT, new Highlight(...newRanges));
  highlights().set(LEARNING_HIGHLIGHT, new Highlight(...learningRanges));
  setButton('on');
}

/** Marks the conversation now, or once more after a run in progress. */
function refresh(): void {
  if (refreshing) {
    refreshAgain = true;
    return;
  }
  refreshing = markConversation()
    .catch((error: unknown) => console.warn('Langfour: marking words failed:', error))
    .finally(() => {
      refreshing = null;
      if (refreshAgain) {
        refreshAgain = false;
        refresh();
      }
    });
}

function scheduleRefresh(): void {
  if (!enabled || refreshTimer) return;
  refreshTimer = setTimeout(() => {
    refreshTimer = null;
    refresh();
  }, REFRESH_MS);
}

function loadLanguage(): Promise<Language | null> {
  return new Promise((resolve) => getPrefs((prefs) => resolve(toLanguage(prefs.preferredLanguage))));
}

async function turnOn(): Promise<void> {
  enabled = true;
  setButton('loading');
  // Statuses change as words are saved and reviewed elsewhere, so each
  // time marking is switched on it starts from what the background says now.
  byToken.clear();
  reported = false;
  language = await loadLanguage();
  if (!enabled) return;
  if (!language) {
    setButton('failed');
    return;
  }
  refresh();
}

function turnOff(): void {
  enabled = false;
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = null;
  clearMarks();
  closePopup();
  setButton('off');
}

function setEnabled(on: boolean): void {
  void chrome.storage.local.set({ [ENABLED_KEY]: on });
  if (on) void turnOn();
  else turnOff();
}

// ====================== Translation popup ======================

let popup: { host: HTMLElement; shadow: ShadowRoot; range: Range; el: HTMLElement | null } | null = null;

function closePopup(): void {
  popup?.host.remove();
  popup = null;
  highlights().delete(ACTIVE_HIGHLIGHT);
}

/** The word under the pointer, if the click landed on one in an answer. */
function wordAt(x: number, y: number): { range: Range; token: string } | null {
  const caret = document.caretRangeFromPoint?.(x, y);
  const node = caret?.startContainer;
  if (!caret || !node || node.nodeType !== Node.TEXT_NODE || !inAnswer(node)) return null;
  const text = node as Text;
  for (const match of text.data.matchAll(WORD)) {
    const start = match.index!;
    const end = start + match[0].length;
    if (caret.startOffset < start || caret.startOffset > end) continue;
    const range = new Range();
    range.setStart(text, start);
    range.setEnd(text, end);
    // A click past the end of a line puts the caret on that line's last word.
    const hit = Array.from(range.getClientRects()).some(
      (r) => x >= r.left && x <= r.right && y >= r.top && y <= r.bottom,
    );
    return hit ? { range, token: match[0] } : null;
  }
  return null;
}

/** Under the word like in the reader, or above it when there's no room below. */
function placePopup(): void {
  if (!popup?.el) return;
  const gap = 10;
  const word = popup.range.getBoundingClientRect();
  const { width, height } = popup.el.getBoundingClientRect();
  let top = word.bottom + gap;
  if (top + height > window.innerHeight - 8 && word.top - gap - height >= 8) top = word.top - gap - height;
  popup.el.style.top = `${top}px`;
  popup.el.style.left = `${Math.max(8, Math.min(word.left, window.innerWidth - width - 20))}px`;
}

/** Shows one of wordPopup's popups, replacing the one before (the spinner). */
function showInPopup(el: HTMLElement): void {
  if (!popup) return;
  popup.el?.remove();
  popup.shadow.appendChild(el);
  popup.el = el;
  placePopup();
  // The progress line arrives later and makes the popup taller.
  new ResizeObserver(() => (el.isConnected ? placePopup() : undefined)).observe(el);
}

function popupButton(label: string, onClick: () => void): HTMLButtonElement {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'flashcard-btn';
  button.textContent = label;
  button.addEventListener('click', onClick);
  return button;
}

/**
 * Saving a word makes all its forms on the page "learning" right away.
 * Returns a function that puts them back.
 */
function markSaved(...wordIds: number[]): () => void {
  const before = new Map(byToken);
  for (const [token, word] of byToken) {
    if (word && wordIds.includes(word.word_id)) byToken.set(token, { ...word, status: 'learning' });
  }
  refresh();
  return () => {
    for (const [token, word] of before) byToken.set(token, word);
    refresh();
  };
}

/** As in the reader: the marks turning "learning" are the confirmation. */
function saveWord(word: ClassifiedWord, wordId: number): void {
  closePopup();
  const undo = markSaved(word.word_id, wordId);
  sendToBackground<{ success: boolean; error?: string }>({ type: 'ADD_WORD_TO_USERWORDS', wordId }, (response) => {
    if (response?.success) return;
    console.error('Langfour: could not save the word:', response?.error ?? 'no answer from the background');
    undo();
  });
}

function openPopup(range: Range, token: string, word: ClassifiedWord, lang: Language): void {
  closePopup();
  if (!overlay) return;
  const host = document.createElement('div');
  host.style.pointerEvents = 'auto';
  const shadow = host.attachShadow({ mode: 'open' });
  const style = document.createElement('style');
  style.textContent = POPUP_CSS;
  shadow.appendChild(style);
  overlay.appendChild(host);
  const current: NonNullable<typeof popup> = { host, shadow, range, el: null };
  popup = current;
  const active = new Highlight(range);
  active.priority = 1;
  highlights().set(ACTIVE_HIGHLIGHT, active);
  showInPopup(createLoadingPopup(token));

  // How the user's reviews of a saved word went, as in the reader.
  const withProgress = (el: HTMLElement) => {
    if (word.status === 'learning' || word.status === 'known') appendWordProgress(el, word.word_id);
    return el;
  };
  void translate(token, lang).then((translation) => {
    if (popup !== current) return;
    if (translation === SIGNED_OUT) {
      const el = createMessagePopup(token, 'Sign in to see translations and save words.');
      el.appendChild(popupButton('Sign in', () => {
        closePopup();
        sendToBackground({ type: 'OPEN_SIGN_IN' });
      }));
      showInPopup(el);
    } else if (!translation) {
      const el = withProgress(createMessagePopup(token, 'Could not load the translation.'));
      el.appendChild(popupButton('Try again', () => openPopup(range, token, word, lang)));
      showInPopup(el);
    } else {
      // Only new words can be saved: saving a word the user already has
      // resets it to learning.
      const save = translation.id && word.status === 'new'
        ? popupButton('Add to flashcards', () => saveWord(word, translation.id))
        : undefined;
      showInPopup(withProgress(createWordPopup(token, translation, lang, save)));
    }
  });
}

/**
 * A double click on a new word saves it without the popup. The marks turn
 * "learning" at once; the save itself waits for the translation, whose id is
 * the word's base form, the one the popup's button saves.
 */
function onDoubleClick(event: MouseEvent): void {
  if (popup && event.composedPath().includes(popup.host)) return;
  closePopup();
  if (!enabled || !language) return;
  const hit = wordAt(event.clientX, event.clientY);
  const word = hit && byToken.get(hit.token);
  if (!hit || !word || word.status !== 'new') return;
  window.getSelection()?.removeAllRanges();
  const undo = markSaved(word.word_id);
  void translate(hit.token, language).then((translation) => {
    undo();
    if (translation && translation !== SIGNED_OUT && translation.id) saveWord(word, translation.id);
    else console.error('Langfour: could not save the word: no translation');
  });
}

function onClick(event: MouseEvent): void {
  // Clicks inside the popup are its own ("Add to flashcards").
  if (popup && event.composedPath().includes(popup.host)) return;
  closePopup();
  if (!enabled || !language) return;
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  // Selecting text (a drag, a double click) is not asking for a translation.
  if (!window.getSelection()?.isCollapsed) return;
  if ((event.target as Element | null)?.closest?.('a, button, input, textarea, [contenteditable="true"]')) return;
  const hit = wordAt(event.clientX, event.clientY);
  const word = hit && byToken.get(hit.token);
  if (hit && word) openPopup(hit.range, hit.token, word, language);
}

// Scrolling yourself closes the popup. ChatGPT also scrolls by itself while
// an answer streams in; then the popup follows its word instead.
const SCROLL_KEYS = new Set(['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' ']);
function onUserScroll(event: Event): void {
  if (popup && !event.composedPath().includes(popup.host)) closePopup();
}

let followFrame = 0;
function followWord(): void {
  if (!popup || followFrame) return;
  followFrame = requestAnimationFrame(() => {
    followFrame = 0;
    if (!popup) return;
    if (!popup.range.startContainer.isConnected) return closePopup();
    placePopup();
  });
}

// ====================== Page styles, the button and its tooltip ======================

// Highlights are painted by the page, so their styles go in the page.
// ChatGPT puts `dark` on <html> in its dark theme.
const HIGHLIGHT_CSS = `
  ::highlight(${NEW_HIGHLIGHT}) { background-color: rgba(255, 214, 10, 0.45); }
  ::highlight(${LEARNING_HIGHLIGHT}) { text-decoration: underline 2px #d9a760; }
  .dark ::highlight(${NEW_HIGHLIGHT}) { background-color: rgba(250, 204, 21, 0.32); }
  .dark ::highlight(${LEARNING_HIGHLIGHT}) { text-decoration: underline 2px #e0a87d; }
  ::highlight(${ACTIVE_HIGHLIGHT}) { background-color: rgba(255, 200, 125, 0.25); color: #8b4513; }
  .dark ::highlight(${ACTIVE_HIGHLIGHT}) { background-color: rgba(224, 168, 125, 0.3); color: #e0a87d; }
`;

const FONT = '-apple-system-body, ui-sans-serif, -apple-system, system-ui, "Segoe UI", Helvetica, Arial, sans-serif';

// The button lives in a shadow root, so ChatGPT's styles don't reach it.
// Its measurements are ChatGPT's Share button's (36px tall, 8px corners,
// 14px text, no border, a grey wash on hover).
const BUTTON_CSS = `
  :host { all: initial; display: flex; align-items: center; pointer-events: auto; }
  button {
    display: inline-flex; align-items: center; gap: 4px; height: 36px; padding: 0 12px 0 10px;
    font: 400 14px/18px ${FONT}; white-space: nowrap;
    color: #0d0d0d; background: #fff; border: 1px solid transparent; border-radius: 8px; cursor: pointer;
  }
  /* Solid, like ChatGPT's own header actions, so a message scrolling
     under the header doesn't show through. */
  button:hover { background: #efefef; }
  button:focus-visible { outline: 2px solid #0d0d0d; outline-offset: 0; }
  .icon { display: inline-flex; width: 20px; height: 20px; border-radius: 5px; }
  .icon svg { width: 20px; height: 20px; fill: currentColor; }
  /* On: the glyph sits on a highlighter-yellow square, like a marked word. */
  button[aria-pressed="true"] .icon { background: rgba(255, 214, 10, 0.55); }
  :host-context(.dark) button { color: #fff; background: #212121; }
  :host-context(.dark) button:hover { background: #383838; }
  :host-context(.dark) button:focus-visible { outline-color: #fff; }
  :host-context(.dark) button[aria-pressed="true"] .icon { background: rgba(250, 204, 21, 0.35); }
`;

// ChatGPT's own tooltip: a black pill 6px under the button.
const TOOLTIP_CSS = `
  :host { all: initial; position: fixed; z-index: 1; pointer-events: none; }
  div {
    font: 400 14px/18px ${FONT}; white-space: nowrap; color: #fff; background: #0d0d0d;
    padding: 5px 12px; border-radius: 16px; box-shadow: 0 8px 18px rgba(15, 23, 42, 0.2);
  }
`;

// A "translate" glyph (Material Icons, Apache 2.0): says "language tool"
// without leaning on an emoji, which some systems render as a box.
const TRANSLATE_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12.87 15.07l-2.54-2.51.03-.03A17.52 17.52 0 0 0 14.07 6H17V4h-7V2H8v2H1v1.99h11.17C11.5 7.92 10.44 9.75 9 11.35 8.07 10.32 7.3 9.19 6.69 8h-2c.73 1.63 1.73 3.17 2.98 4.56l-5.09 5.02L4 19l5-5 3.11 3.11.76-2.04zM18.5 10h-2L12 22h2l1.12-3h4.75L21 22h2l-4.5-12zm-2.62 7 1.62-4.33L19.12 17h-3.24z"/></svg>';

type ButtonState = 'off' | 'loading' | 'on' | 'signed-out' | 'failed';

const TOOLTIPS: Record<ButtonState, string> = {
  off: 'Highlight words to learn',
  loading: 'Checking words…',
  on: 'Hide word highlights',
  'signed-out': 'Sign in to Langfour first',
  failed: 'Couldn’t check words, try again',
};

let tooltip: { host: HTMLElement; text: HTMLElement } | null = null;

function showTooltip(): void {
  if (!button || !overlay) return;
  if (!tooltip) {
    const host = document.createElement('div');
    const shadow = host.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = TOOLTIP_CSS;
    const text = document.createElement('div');
    text.setAttribute('role', 'tooltip');
    shadow.append(style, text);
    tooltip = { host, text };
  }
  tooltip.text.textContent = TOOLTIPS[(button.dataset.state as ButtonState) ?? 'off'];
  overlay.appendChild(tooltip.host);
  const rect = button.getBoundingClientRect();
  const width = tooltip.host.getBoundingClientRect().width;
  const left = Math.min(rect.left + rect.width / 2 - width / 2, window.innerWidth - width - 8);
  tooltip.host.style.left = `${Math.max(8, left)}px`;
  tooltip.host.style.top = `${rect.bottom + 6}px`;
}

function hideTooltip(): void {
  tooltip?.host.remove();
}

function setButton(state: ButtonState): void {
  if (!button) return;
  button.dataset.state = state;
  button.setAttribute('aria-pressed', String(state === 'on' || state === 'loading'));
  button.setAttribute('aria-label', `Langfour: ${TOOLTIPS[state]}`);
  if (tooltip?.host.isConnected) showTooltip();
  // Without marks to show, the next click switches marking on again.
  if (state === 'signed-out' || state === 'failed') {
    enabled = false;
    clearMarks();
    button.setAttribute('aria-pressed', 'false');
  }
}

function createButton(): HTMLElement {
  const host = document.createElement('div');
  host.id = 'langfour-highlight-toggle';
  const shadow = host.attachShadow({ mode: 'open' });
  const style = document.createElement('style');
  style.textContent = BUTTON_CSS;
  button = document.createElement('button');
  button.type = 'button';
  button.innerHTML = `<span class="icon">${TRANSLATE_ICON}</span><span>Langfour</span>`;
  button.addEventListener('click', () => setEnabled(!enabled));
  button.addEventListener('mouseenter', showTooltip);
  button.addEventListener('mouseleave', hideTooltip);
  button.addEventListener('focus', showTooltip);
  button.addEventListener('blur', hideTooltip);
  shadow.append(style, button);
  setButton('off');
  return host;
}

/**
 * Keeps the button in the header, just left of "…". ChatGPT wraps each
 * header action in its own element; the button goes before the first one.
 * Pages without those actions (a new chat) have no button. React re-renders
 * the header on navigation, so this runs again on every page change.
 */
function placeButton(): void {
  if (!buttonHost) return;
  const surface = document.querySelector(HEADER_ACTIONS);
  let action: Element | null | undefined = surface?.querySelector('button');
  while (action?.parentElement && action.parentElement !== surface && action.parentElement.querySelectorAll('button').length < 2) {
    action = action.parentElement;
  }
  if (!action?.parentElement) {
    buttonHost.remove();
    hideTooltip();
    return;
  }
  if (buttonHost.nextElementSibling !== action) action.parentElement.insertBefore(buttonHost, action);
}

function init(): void {
  if (!supported()) return;
  // Reloading the extension starts a new copy of this script beside the old
  // one, which can no longer reach the background. The old copy steps aside,
  // or the two buttons would keep moving in front of each other.
  document.dispatchEvent(new CustomEvent(STARTED_EVENT));
  const style = document.createElement('style');
  style.textContent = HIGHLIGHT_CSS;
  document.head.appendChild(style);
  overlay = document.createElement('div');
  overlay.id = 'langfour-overlay';
  Object.assign(overlay.style, { position: 'fixed', inset: '0', zIndex: '2147483000', pointerEvents: 'none' });
  document.documentElement.appendChild(overlay);
  buttonHost = createButton();
  placeButton();

  const observer = new MutationObserver(() => {
    placeButton();
    scheduleRefresh();
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  const onKey = (event: KeyboardEvent) => {
    if (event.key === 'Escape') closePopup();
    else if (SCROLL_KEYS.has(event.key) && !(event.target as Element | null)?.closest?.('textarea, input, [contenteditable="true"]')) closePopup();
  };
  document.addEventListener('click', onClick, true);
  document.addEventListener('dblclick', onDoubleClick, true);
  document.addEventListener('keydown', onKey);
  document.addEventListener('scroll', followWord, { capture: true, passive: true });
  document.addEventListener('wheel', onUserScroll, { capture: true, passive: true });
  document.addEventListener('touchmove', onUserScroll, { capture: true, passive: true });
  window.addEventListener('resize', followWord);
  document.addEventListener(STARTED_EVENT, () => {
    turnOff();
    observer.disconnect();
    document.removeEventListener('click', onClick, true);
    document.removeEventListener('dblclick', onDoubleClick, true);
    document.removeEventListener('keydown', onKey);
    document.removeEventListener('scroll', followWord, { capture: true });
    document.removeEventListener('wheel', onUserScroll, { capture: true });
    document.removeEventListener('touchmove', onUserScroll, { capture: true });
    window.removeEventListener('resize', followWord);
    style.remove();
    buttonHost?.remove();
    overlay?.remove();
    buttonHost = null;
  }, { once: true });

  chrome.storage.local.get(ENABLED_KEY).then((stored) => {
    if (stored[ENABLED_KEY]) void turnOn();
  });
  // A new language or account means different statuses for every word.
  chrome.storage.onChanged.addListener((changes, area) => {
    const languageChanged = area === 'sync' && changes.preferredLanguage;
    const accountChanged = area === 'local' && changes.supabaseSession;
    if (enabled && (languageChanged || accountChanged)) void turnOn();
  });
}

init();
