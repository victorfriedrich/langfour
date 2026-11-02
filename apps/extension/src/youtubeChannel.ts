// A YouTube channel page's Favourite button and Langfour tab
// (docs/plans/youtube-plan.md, features 4 and 8; the API is
// apps/api/channel_routes.py). youtubeFavourite.ts runs this in the page's
// MAIN world, where YouTube's own elements expose the channel's data.
//
// The tab shows one line about the channel's videos and, when they would make
// a real difference, the channel's core words. Its panel takes the place of
// YouTube's tab content until another tab is chosen.

import type { Language } from './languages';

export type ChannelView = {
  favourite: boolean;
  videos: number;
  at_level: number;
  progress: { added: number; total: number | null } | null;
  core_words: { words: { word_id: number; word: string }[]; before: number; after: number } | null;
};

/** What the API answered: a value, or why there is none. */
export type Answer<T> = { ok: true; value: T } | { ok: false; signedOut: boolean };

export type ChannelApi = {
  favourited(channelId: string): Promise<Answer<{ favourite: boolean }>>;
  view(channelId: string, language: Language): Promise<Answer<ChannelView>>;
  favourite(channelId: string, language: Language, favourite: boolean): Promise<Answer<{ favourite: boolean }>>;
  addCoreWords(channelId: string, language: Language): Promise<Answer<{ added: string[] }>>;
  signIn(): void;
};

const MARK = 'data-langfour-channel';
const CHIPS_SHOWN = 15;
const CHANNEL_ID = /^UC[A-Za-z0-9_-]{22}$/;
// While the tab is open: soon after a favourite, whose uploads are being listed
// in the background, then slowly while videos are still arriving.
const AFTER_FAVOURITE_MS = 5_000;
const AFTER_FAVOURITE_FOR_MS = 20_000;
const WHILE_ADDING_MS = 60_000;

const BROWSE = 'ytd-browse[page-subtype="channels"]';
// YouTube renames these now and then; they are kept here, in one place.
const SELECTORS = {
  actions: `${BROWSE} yt-flexible-actions-view-model`,
  tabs: `${BROWSE} yt-tab-group-shape .tabGroupShapeTabs`,
  // The selected tab's underline: one bar YouTube slides under it.
  slider: `${BROWSE} yt-tab-group-shape .tabGroupShapeSlider`,
  content: `${BROWSE} ytd-two-column-browse-results-renderer`,
};

// ---------------------------------------------------------------- reading ──

/** The channel's UC id. A @handle page has it only in YouTube's own data. */
export function channelIdOf(doc: Document, pathname: string): string | null {
  type BrowseData = { metadata?: { channelMetadataRenderer?: { externalId?: unknown } } };
  const browse = doc.querySelector(BROWSE) as (Element & { data?: BrowseData }) | null;
  const fromData = browse?.data?.metadata?.channelMetadataRenderer?.externalId;
  if (typeof fromData === 'string' && CHANNEL_ID.test(fromData)) return fromData;
  const fromPath = pathname.match(/^\/channel\/([^/?#]+)/)?.[1];
  return fromPath && CHANNEL_ID.test(fromPath) ? fromPath : null;
}

/**
 * The channel a yt-navigate-finish event is for. It has to come from the event:
 * YouTube fires it before handing the page its new data, so at that moment the
 * page's data and header are still the previous channel's.
 */
export function navigatedChannelId(detail: unknown): string | null {
  type Navigation = {
    response?: { response?: { metadata?: { channelMetadataRenderer?: { externalId?: unknown } } } };
    endpoint?: { browseEndpoint?: { browseId?: unknown } };
  };
  const navigation = detail as Navigation | null | undefined;
  const id = navigation?.response?.response?.metadata?.channelMetadataRenderer?.externalId
    ?? navigation?.endpoint?.browseEndpoint?.browseId;
  return typeof id === 'string' && CHANNEL_ID.test(id) ? id : null;
}

export function isChannelPath(pathname: string): boolean {
  return /^\/(channel\/|@|c\/|user\/)/.test(pathname);
}

// --------------------------------------------------------------- the line ──

const videosText = (n: number) => (n === 1 ? '1 video' : `${n} videos`);

/** The line at the top of the tab. */
export function summaryText(view: ChannelView): string {
  const level = `${view.at_level} at your level`;
  if (view.progress) {
    const { added, total } = view.progress;
    const count = total === null ? videosText(added) : `${added} of ${videosText(total)}`;
    return `${count} added · ${level}`;
  }
  if (view.videos) return `${videosText(view.videos)} indexed · ${level}`;
  return view.favourite
    ? 'No videos from this channel are indexed yet.'
    : 'No videos from this channel are indexed yet. Favourite it to add them.';
}

// ------------------------------------------------------------------ style ──

const STYLE_ID = 'langfour-channel-style';
const ACCENT = '#4f46e5';
// YouTube's own theme colours, so the panel follows its light and dark mode.
// It renamed them once (--yt-spec-* to --yt-sys-color-baseline--*); the old
// names stay as fallbacks.
const CSS = `
.lf-fav,.lf-panel{--lf-text:var(--yt-sys-color-baseline--text-primary,var(--yt-spec-text-primary,#0f0f0f));--lf-text-2:var(--yt-sys-color-baseline--text-secondary,var(--yt-spec-text-secondary,#606060));--lf-line:var(--yt-sys-color-baseline--outline,var(--yt-spec-10-percent-layer,rgba(0,0,0,.1)));--lf-chip:var(--yt-sys-color-baseline--tonal-background,var(--yt-spec-badge-chip-background,rgba(0,0,0,.05)));}
.lf-fav{display:inline-flex;align-items:center;gap:6px;height:36px;padding:0 16px;border-radius:18px;font:500 14px/1 Roboto,Arial,sans-serif;cursor:pointer;border:0;background:var(--lf-chip);color:var(--lf-text);}
.lf-fav:hover{background:var(--yt-sys-color-baseline--button-chip-background-hover,rgba(0,0,0,.1));}
.lf-fav:disabled{cursor:default;}
.lf-fav[aria-pressed="true"] svg{color:${ACCENT};}
html[dark] .lf-fav[aria-pressed="true"] svg{color:#a5b4fc;}
.lf-panel{padding:24px 0;font:400 14px/20px Roboto,Arial,sans-serif;color:var(--lf-text);max-width:720px;}
.lf-panel p{margin:0;}
.lf-muted{color:var(--lf-text-2);}
.lf-card{margin-top:24px;padding:16px;border:1px solid var(--lf-line);border-radius:12px;}
.lf-card h3{margin:0 0 12px;font:500 16px/22px Roboto,Arial,sans-serif;}
.lf-chips{display:flex;flex-wrap:wrap;gap:8px;margin:0;padding:0;list-style:none;}
.lf-chips li,.lf-more{padding:6px 12px;border-radius:8px;background:var(--lf-chip);font:inherit;color:inherit;border:0;}
.lf-chips li.lf-more-item{padding:0;background:none;}
.lf-more{cursor:pointer;}
.lf-foot{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-top:16px;}
.lf-add{height:36px;padding:0 16px;border-radius:8px;border:0;background:${ACCENT};color:#fff;font:500 14px/1 Roboto,Arial,sans-serif;cursor:pointer;}
.lf-add:disabled{opacity:.6;cursor:default;}
.lf-signin{margin-top:12px;}
`;

function ensureStyle(doc: Document): void {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = CSS;
  doc.head.appendChild(style);
}

function star(doc: Document, filled: boolean): SVGElement {
  const ns = 'http://www.w3.org/2000/svg';
  const icon = doc.createElementNS(ns, 'svg');
  icon.setAttribute('viewBox', '0 0 24 24');
  icon.setAttribute('width', '16');
  icon.setAttribute('height', '16');
  icon.setAttribute('aria-hidden', 'true');
  const path = doc.createElementNS(ns, 'path');
  path.setAttribute('d', 'M12 3.8l2.5 5.2 5.7.8-4.1 4 1 5.7-5.1-2.7-5.1 2.7 1-5.7-4.1-4 5.7-.8z');
  path.setAttribute('fill', filled ? 'currentColor' : 'none');
  path.setAttribute('stroke', 'currentColor');
  path.setAttribute('stroke-width', '1.8');
  path.setAttribute('stroke-linejoin', 'round');
  icon.appendChild(path);
  return icon;
}

// ---------------------------------------------------------------- the tab ──

function el<K extends keyof HTMLElementTagNameMap>(doc: Document, tag: K, className = '', text = ''): HTMLElementTagNameMap[K] {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function coreWordsCard(doc: Document, words: NonNullable<ChannelView['core_words']>, add: () => Promise<boolean>): HTMLElement {
  const card = el(doc, 'section', 'lf-card');
  const n = words.words.length;
  card.append(el(doc, 'h3', '', `${n} core ${n === 1 ? 'word' : 'words'} you don't know yet`));

  const chips = el(doc, 'ul', 'lf-chips');
  const chip = (word: string) => chips.appendChild(el(doc, 'li', '', word));
  words.words.slice(0, CHIPS_SHOWN).forEach((w) => chip(w.word));
  const hidden = words.words.slice(CHIPS_SHOWN);
  if (hidden.length) {
    const more = el(doc, 'button', 'lf-more', `+ ${hidden.length} more`);
    more.type = 'button';
    const item = el(doc, 'li', 'lf-more-item');
    more.addEventListener('click', () => {
      item.remove();
      hidden.forEach((w) => chip(w.word));
    });
    item.append(more);
    chips.append(item);
  }
  card.append(chips);

  const foot = el(doc, 'div', 'lf-foot');
  const button = el(doc, 'button', 'lf-add', `Add ${n} to my reviews`);
  button.type = 'button';
  button.addEventListener('click', async () => {
    button.disabled = true;
    const added = await add();
    button.textContent = added ? 'Added to your reviews' : 'Could not add them. Try again';
    button.disabled = added;
  });
  foot.append(el(doc, 'span', '', `${words.before.toFixed(1)}% → ${words.after.toFixed(1)}% understood`), button);
  card.append(foot);
  return card;
}

/** The tab's content for a channel, or a sign-in prompt. */
export function renderPanel(
  doc: Document,
  answer: Answer<ChannelView>,
  addCoreWords: () => Promise<boolean>,
  signIn: () => void,
): HTMLElement {
  const panel = el(doc, 'div', 'lf-panel');
  panel.setAttribute(MARK, 'panel');
  panel.setAttribute('role', 'tabpanel');
  if (!answer.ok) {
    panel.append(el(doc, 'p', 'lf-muted', answer.signedOut
      ? 'Sign in to Langfour to see how much of this channel you understand.'
      : 'Langfour could not load this channel. Try again later.'));
    if (answer.signedOut) {
      const button = el(doc, 'button', 'lf-add lf-signin', 'Sign in');
      button.type = 'button';
      button.addEventListener('click', signIn);
      panel.append(button);
    }
    return panel;
  }
  panel.append(el(doc, 'p', 'lf-summary', summaryText(answer.value)));
  if (answer.value.core_words) panel.append(coreWordsCard(doc, answer.value.core_words, addCoreWords));
  return panel;
}

// --------------------------------------------------------------- mounting ──

let dispose: (() => void) | null = null;
// Bumped by every mount, so one still waiting for YouTube's header gives up
// once a later navigation has started its own.
let generation = 0;

/** Takes the page's Langfour elements out and gives YouTube its tab back. */
export function unmount(doc: Document): void {
  generation += 1;
  dispose?.();
  dispose = null;
  doc.querySelectorAll(`[${MARK}]`).forEach((node) => node.remove());
}

function favouriteButton(doc: Document, channelId: string, language: Language, initial: boolean, api: ChannelApi, onChange: (on: boolean) => void): HTMLElement {
  const wrap = el(doc, 'div', 'ytFlexibleActionsViewModelAction');
  wrap.setAttribute(MARK, 'favourite');
  const button = el(doc, 'button', 'lf-fav');
  button.type = 'button';
  const show = (on: boolean) => {
    button.setAttribute('aria-pressed', String(on));
    button.replaceChildren(star(doc, on), doc.createTextNode(on ? 'Favourited' : 'Favourite'));
  };
  show(initial);
  button.addEventListener('click', async () => {
    const want = button.getAttribute('aria-pressed') !== 'true';
    button.disabled = true;
    show(want);
    const answer = await api.favourite(channelId, language, want);
    button.disabled = false;
    if (!answer.ok) {
      show(!want);
      if (answer.signedOut) api.signIn();
      return;
    }
    show(answer.value.favourite);
    onChange(answer.value.favourite);
  });
  wrap.append(button);
  return wrap;
}

function langfourTab(doc: Document, open: () => void): HTMLElement {
  const tab = el(doc, 'div', 'ytTabShapeHost ytTabShapeHostClickable');
  tab.setAttribute(MARK, 'tab');
  tab.setAttribute('role', 'tab');
  tab.setAttribute('tabindex', '0');
  tab.setAttribute('aria-selected', 'false');
  tab.append(el(doc, 'div', 'ytTabShapeTab', 'Langfour'), el(doc, 'div', 'ytTabShapeTabBar'));
  tab.addEventListener('click', open);
  tab.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      open();
    }
  });
  return tab;
}

/**
 * Puts the button and tab where they belong, if they aren't there. YouTube
 * rebuilds its header when the layout changes, such as on a window resize, and
 * drops what it didn't render.
 */
function place(doc: Document, button: HTMLElement, tab: HTMLElement): void {
  const actions = doc.querySelector(SELECTORS.actions);
  if (actions && button.parentElement !== actions) actions.append(button);
  const tabs = doc.querySelector(SELECTORS.tabs);
  if (tabs && tab.parentElement !== tabs) {
    // Before YouTube's search, which it keeps last.
    const last = tabs.querySelector('.ytTabShapeLastTab');
    tabs.insertBefore(tab, last && last.parentElement === tabs ? last : null);
  }
}

const SELECTED = [['.ytTabShapeTab', 'ytTabShapeTabSelected'], ['.ytTabShapeTabBar', 'ytTabShapeTabBarSelected']];

function select(tab: Element, on: boolean): void {
  tab.setAttribute('aria-selected', String(on));
  for (const [part, cls] of SELECTED) tab.querySelector(part)?.classList.toggle(cls, on);
}

/** The channel showing, once YouTube's data is for the channel navigated to. */
async function waitForChannel(doc: Document, pathname: string, expectedId: string | null, isCurrent: () => boolean, timeoutMs = 10_000): Promise<string | null> {
  const wanted = expectedId ?? pathname.match(/^\/channel\/([^/?#]+)/)?.[1] ?? null;
  const start = Date.now();
  while (isCurrent() && Date.now() - start < timeoutMs) {
    const id = channelIdOf(doc, pathname);
    if (id && (!wanted || id === wanted)) return id;
    await new Promise((r) => setTimeout(r, 100));
  }
  return null;
}

/**
 * Adds the Favourite button and the Langfour tab to the channel page that is
 * showing. Safe to call on every navigation: what a previous page added is
 * taken out first. `expectedId` is the channel the navigation was to
 * (navigatedChannelId), or null when there was none, as on a first load.
 */
export async function mountChannelPage(doc: Document, pathname: string, language: Language, api: ChannelApi, expectedId: string | null = null): Promise<void> {
  unmount(doc);
  if (!isChannelPath(pathname)) return;
  const mine = generation;
  const isCurrent = () => mine === generation;
  const channelId = await waitForChannel(doc, pathname, expectedId, isCurrent);
  if (!channelId || !isCurrent()) return;
  // Only this on every channel page; the tab's numbers wait until it opens.
  const favourited = await api.favourited(channelId);
  if (!isCurrent()) return;
  ensureStyle(doc);

  let view: Answer<ChannelView> | null = null;
  let panel: HTMLElement | null = null;
  let previous: Element | null = null;
  let hidden: HTMLElement | null = null;
  let bar: HTMLElement | null = null;
  let barStyle: string | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let requests = 0;
  let favouritedAt = 0;
  let coreWordsAdded = false;

  const renderOpen = () => {
    if (!view) return;
    const next = renderPanel(doc, view, async () => {
      const added = await api.addCoreWords(channelId, language);
      if (!added.ok && added.signedOut) api.signIn();
      coreWordsAdded = added.ok;
      return added.ok;
    }, api.signIn);
    panel?.replaceWith(next);
    panel = next;
  };
  const refresh = async () => {
    clearTimeout(timer);
    const request = ++requests;
    const next = await api.view(channelId, language);
    // The tab closed, or a newer request is on its way.
    if (request !== requests || !panel) return;
    const summary = panel.querySelector('.lf-summary');
    // Only the line changes on a refresh: a redrawn card would fold its words
    // up again and forget that they were added.
    const sameCard = summary && view?.ok && next.ok && (coreWordsAdded
      || JSON.stringify(view.value.core_words) === JSON.stringify(next.value.core_words));
    view = next;
    if (sameCard && next.ok) summary.textContent = summaryText(next.value);
    else renderOpen();
    if (!next.ok) return;
    const delay = Date.now() - favouritedAt < AFTER_FAVOURITE_FOR_MS ? AFTER_FAVOURITE_MS
      : next.value.progress ? WHILE_ADDING_MS : 0;
    if (delay) timer = setTimeout(refresh, delay);
  };
  const open = () => {
    if (panel) return;
    const tabs = doc.querySelector(SELECTORS.tabs);
    previous = tabs?.querySelector(`[aria-selected="true"]:not([${MARK}])`) ?? null;
    if (previous) select(previous, false);
    select(tab, true);
    bar = doc.querySelector(SELECTORS.slider);
    if (bar && tabs) {
      barStyle = bar.getAttribute('style');
      bar.style.width = `${tab.getBoundingClientRect().width}px`;
      bar.style.transform = `translateX(${tab.getBoundingClientRect().left - tabs.getBoundingClientRect().left}px)`;
    }
    hidden = doc.querySelector(SELECTORS.content);
    panel = el(doc, 'div', 'lf-panel lf-muted', 'Loading…');
    panel.setAttribute(MARK, 'panel');
    if (hidden) {
      hidden.style.display = 'none';
      hidden.before(panel);
    }
    view = null;
    void refresh();
  };
  const close = () => {
    clearTimeout(timer);
    requests += 1;
    if (!panel) return;
    panel.remove();
    panel = null;
    select(tab, false);
    if (previous) select(previous, true);
    if (bar && barStyle !== null) bar.setAttribute('style', barStyle);
    barStyle = null;
    // The element hidden, not a new look-up: YouTube may have re-stamped the
    // page or moved on, and a miss would leave it hidden for good.
    if (hidden) hidden.style.display = '';
    hidden = null;
  };

  const button = favouriteButton(doc, channelId, language, favourited.ok && favourited.value.favourite, api, (on) => {
    favouritedAt = on ? Date.now() : 0;
    if (panel) void refresh();
  });
  const tab = langfourTab(doc, open);
  place(doc, button, tab);
  const observer = new MutationObserver(() => place(doc, button, tab));
  observer.observe(doc.querySelector(BROWSE) ?? doc.body, { childList: true, subtree: true });
  // Choosing one of YouTube's tabs, even the one already selected, leaves ours.
  // On the document, as YouTube can replace the tab bar.
  const onTabs = (event: Event) => {
    const target = event.target as Element | null;
    if (target?.closest(`${SELECTORS.tabs} [role="tab"]`) && !target.closest(`[${MARK}]`)) close();
  };
  doc.addEventListener('click', onTabs, true);

  dispose = () => {
    observer.disconnect();
    doc.removeEventListener('click', onTabs, true);
    close();
    button.remove();
    tab.remove();
  };
}
