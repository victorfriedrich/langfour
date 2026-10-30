import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import type { BackgroundMessage } from './messages';

// happy-dom has no CSS Custom Highlight API; a Set of ranges and a Map of
// names is all the script relies on.
class FakeHighlight extends Set<AbstractRange> {
  constructor(...ranges: AbstractRange[]) {
    super(ranges);
  }
}
const registry = new Map<string, FakeHighlight>();

// ChatGPT's page as of 2026-10: the header's actions ("…", Share) each in
// their own wrapper, prompts and answers somewhere under <main>.
const PAGE = `
  <header><div data-testid="app-shell-header-context-menu-surface"><div class="actions">
    <div class="dots"><div><button aria-label="Chat actions">…</button></div></div>
    <div class="share"><div><button aria-label="Share">Share</button></div></div>
  </div></div></header>
  <main>
    <div data-content-search-unit-key="turn-0:0:user"><p>Hola, el perro</p></div>
    <div data-content-search-unit-key="turn-0:2:assistant">
      <p id="answer">El perro corre <strong>rápido</strong>.</p>
      <pre><code>perro = corre</code></pre>
      <button>Copy perro</button>
    </div>
  </main>
  <nav>perro</nav>
`;

const STATUSES: Record<string, string> = { perro: 'new', corre: 'learning', rápido: 'known', El: 'known' };

beforeEach(async () => {
  vi.resetModules();
  registry.clear();
  vi.stubGlobal('Highlight', FakeHighlight);
  vi.stubGlobal('CSS', { highlights: registry });
  document.head.innerHTML = '';
  document.body.innerHTML = PAGE;
  await chrome.storage.sync.set({ preferredLanguage: 'es', preferredLanguageResolved: true });
  vi.mocked(chrome.runtime.sendMessage).mockImplementation(((message: BackgroundMessage, callback: (value: unknown) => void) => {
    if (message.type === 'CLASSIFY_WORDS') {
      callback({
        ok: true,
        words: message.tokens.filter((t) => STATUSES[t]).map((token, i) => ({ token, word_id: i + 1, status: STATUSES[token] })),
      });
    }
    if (message.type === 'BACKEND_FETCH') {
      callback({ ok: true, status: 200, statusText: 'OK', body: JSON.stringify({ id: '77', root: 'el perro', translation: 'dog' }) });
    }
  }) as unknown as typeof chrome.runtime.sendMessage);
});

afterEach(() => {
  vi.restoreAllMocks();
  document.getElementById('langfour-highlight-toggle')?.remove();
  document.getElementById('langfour-overlay')?.remove();
});

const marked = (name: string) => Array.from(registry.get(name) ?? []).map((range) => (range as Range).toString());
const host = () => document.getElementById('langfour-highlight-toggle');
const toggle = () => host()!.shadowRoot!.querySelector('button')!;

it('reads only ChatGPT’s answers: not prompts, code, buttons or the page around them', async () => {
  const { wordsIn } = await import('./chatgptHighlight');
  expect(wordsIn(document).map((w) => w.token)).toEqual(['El', 'perro', 'corre', 'rápido']);
});

it('sits in the header, just left of the "…" button', async () => {
  await import('./chatgptHighlight');
  expect(host()!.parentElement!.className).toBe('actions');
  expect(host()!.nextElementSibling!.className).toBe('dots');
  expect(toggle().textContent).toBe('Langfour');

  // ChatGPT re-renders the header when switching chats.
  document.querySelector('header')!.outerHTML = PAGE.match(/<header>[\s\S]*<\/header>/)![0];
  await vi.waitFor(() => expect(host()!.nextElementSibling?.className).toBe('dots'));
});

it('highlights new words and underlines learning ones when switched on, and clears them when off', async () => {
  await import('./chatgptHighlight');
  toggle().click();
  await vi.waitFor(() => expect(marked('langfour-new')).toEqual(['perro']));
  expect(marked('langfour-learning')).toEqual(['corre']);
  expect(toggle().getAttribute('aria-pressed')).toBe('true');
  expect(toggle().getAttribute('aria-label')).toBe('Langfour: Hide word highlights');
  expect((chrome.storage.local as unknown as { __store: Map<string, unknown> }).__store.get('chatgptHighlightOn')).toBe(true);

  toggle().click();
  expect(registry.size).toBe(0);
  expect(toggle().getAttribute('aria-pressed')).toBe('false');
});

it('shows a ChatGPT-style tooltip under the button on hover', async () => {
  await import('./chatgptHighlight');
  toggle().dispatchEvent(new MouseEvent('mouseenter'));
  const tip = document.querySelector('#langfour-overlay > div')!.shadowRoot!.querySelector('[role="tooltip"]')!;
  expect(tip.textContent).toBe('Highlight words to learn');
  toggle().dispatchEvent(new MouseEvent('mouseleave'));
  expect(document.querySelector('#langfour-overlay > div')).toBeNull();
});

it('marks words that arrive later, such as a streamed answer', async () => {
  await chrome.storage.local.set({ chatgptHighlightOn: true });
  await import('./chatgptHighlight');
  await vi.waitFor(() => expect(marked('langfour-new')).toEqual(['perro']));

  const reply = document.createElement('p');
  reply.textContent = 'Otro perro';
  document.querySelector('main')!.appendChild(reply);
  await vi.waitFor(() => expect(marked('langfour-new')).toEqual(['perro', 'perro']), { timeout: 2000 });
});

it('opens the reader’s word popup on a click on a word, and saving makes it a learning word', async () => {
  await chrome.storage.local.set({ chatgptHighlightOn: true });
  await import('./chatgptHighlight');
  await vi.waitFor(() => expect(marked('langfour-new')).toEqual(['perro']));

  // happy-dom does no layout: point the click at "perro" by hand.
  const text = document.getElementById('answer')!.firstChild as Text;
  document.caretRangeFromPoint = () => {
    const caret = new Range();
    caret.setStart(text, text.data.indexOf('perro') + 2);
    return caret;
  };
  vi.spyOn(Range.prototype, 'getClientRects').mockReturnValue([{ left: 0, right: 50, top: 0, bottom: 20 }] as unknown as DOMRectList);
  document.getElementById('answer')!.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 10, clientY: 10 }));
  expect(marked('langfour-active')).toEqual(['perro']);

  const popup = () => Array.from(document.querySelectorAll('#langfour-overlay > div'))
    .map((host) => host.shadowRoot?.querySelector<HTMLElement>('.word-popup'))
    .find(Boolean);
  await vi.waitFor(() => expect(popup()?.querySelector('.translations-container')?.textContent).toBe('dog'));
  expect(popup()!.querySelector('.popup-header')!.textContent).toBe('perro (el perro)');

  const save = popup()!.querySelector<HTMLButtonElement>('.flashcard-btn')!;
  expect(save.textContent).toBe('Add to flashcards');
  save.click();
  expect(vi.mocked(chrome.runtime.sendMessage)).toHaveBeenCalledWith({ type: 'ADD_WORD_TO_USERWORDS', wordId: 77 }, expect.any(Function));
  expect(popup()).toBeUndefined();
  await vi.waitFor(() => expect(marked('langfour-learning')).toEqual(['perro', 'corre']));
  expect(marked('langfour-new')).toEqual([]);
});

it('says to sign in when there is no session', async () => {
  vi.mocked(chrome.runtime.sendMessage).mockImplementation(((_: unknown, callback: (value: unknown) => void) =>
    callback({ ok: false, error: 'No Supabase session available' })) as unknown as typeof chrome.runtime.sendMessage);
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  await import('./chatgptHighlight');
  toggle().click();
  await vi.waitFor(() => expect(toggle().getAttribute('aria-label')).toBe('Langfour: Sign in to Langfour first'));
  expect(toggle().getAttribute('aria-pressed')).toBe('false');
});

// The language check (userdata.chatgpt_language_check): the API says, per
// paragraph, which of the words to mark are Spanish in that spot.
function answerChecks(check: (request: { path: string; method: string; body?: unknown }) => { status: number; body: unknown }) {
  const requests: { path: string; method: string; body?: unknown }[] = [];
  const classify = vi.mocked(chrome.runtime.sendMessage).getMockImplementation()!;
  vi.mocked(chrome.runtime.sendMessage).mockImplementation(((message: BackgroundMessage, callback: (value: unknown) => void) => {
    if (message.type === 'BACKEND_FETCH' && message.path === '/api/language-check') {
      requests.push(message);
      const { status, body } = check(message);
      callback({ ok: status === 200, status, statusText: String(status), body: JSON.stringify(body) });
      return;
    }
    return (classify as unknown as (m: BackgroundMessage, c: (value: unknown) => void) => void)(message, callback);
  }) as unknown as typeof chrome.runtime.sendMessage);
  return requests;
}

it('leaves words the language check calls English unmarked, once the paragraph stops changing', async () => {
  const requests = answerChecks((request) => request.method === 'GET'
    ? { status: 200, body: { enabled: true } }
    : { status: 200, body: { blocks: [{ in_language: [false, true] }] } });
  await import('./chatgptHighlight');
  toggle().click();
  await vi.waitFor(() => expect(marked('langfour-learning')).toEqual(['corre']), { timeout: 3000 });
  expect(marked('langfour-new')).toEqual([]);

  const posts = requests.filter((r) => r.method === 'POST');
  expect(posts).toHaveLength(1);
  expect(posts[0].body).toEqual({
    language: 'es',
    blocks: [{ text: 'El perro corre rápido.', before: '', after: '', words: [[3, 8], [9, 14]] }],
  });
});

it('marks as before when the account has the language check off', async () => {
  const requests = answerChecks(() => ({ status: 200, body: { enabled: false } }));
  await import('./chatgptHighlight');
  toggle().click();
  await vi.waitFor(() => expect(marked('langfour-new')).toEqual(['perro']));
  expect(requests.map((r) => r.method)).toEqual(['GET']);
});

it('marks as before when the language check fails', async () => {
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  answerChecks((request) => request.method === 'GET'
    ? { status: 200, body: { enabled: true } }
    : { status: 502, body: {} });
  await import('./chatgptHighlight');
  toggle().click();
  await vi.waitFor(() => expect(marked('langfour-new')).toEqual(['perro']), { timeout: 3000 });
  expect(marked('langfour-learning')).toEqual(['corre']);
});
