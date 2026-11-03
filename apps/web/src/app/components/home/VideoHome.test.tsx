import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { UserContext } from '@/context/UserContext';
import VideoHome from './VideoHome';
import type { HomePage, HomeVideo } from './homeApi';

const extension = vi.hoisted(() => ({ state: 'installed' as 'installed' | 'missing' }));
vi.mock('../../hooks/useExtensionStatus', () => ({
  useExtensionStatus: () =>
    extension.state === 'missing'
      ? { state: 'missing' }
      : { state: 'installed', version: '1', signedIn: true, email: null },
}));

const card = (id: string, title: string, channel: string | null, extra: Partial<HomeVideo> = {}): HomeVideo => ({
  id, title, channel, duration_s: 1348, understood: 96.4, new_words: 14, watched_share: null, ...extra,
});

const NIGHT = card('aaaaaaaaaaa', 'En este lugar no existe la noche: 24 horas de sol', 'Katy Travels');
const BUTLER = card('bbbbbbbbbbb', 'Soy mayordomo de un multimillonario en Nueva York', 'Molaviajar');
const BASURERO = card('ccccccccccc', 'El basurero de ropa más grande del mundo', 'Ary Tenorio', {
  watched_share: 0.42, duration_s: 1045,
});

const PAGE: HomePage = {
  videos: [NIGHT, BUTLER, BASURERO],
  total: 3,
  topics: ['Gaming', 'Travel'],
  levels: { A1: 27, A2: 312, B1: 5019, B2: 9130, C1: 44 },
  empty: null,
  channels: [{
    name: 'Ary Tenorio', channel_id: 'UC' + 'a'.repeat(22), following: false, understood: 96, videos: 8,
    best: [card('ddddddddddd', 'Cazando ofertas en Tepito', 'Ary Tenorio', { duration_s: 900 })],
  }],
};

const EMPTY: HomePage = {
  videos: [], total: 0, topics: ['Gaming', 'Travel'],
  levels: { A1: 0, A2: 0, B1: 35, B2: 82, C1: 0 },
  empty: {
    nearest_level: 'B1',
    nearest: { count: 35, videos: [card('eeeeeeeeeee', 'Encontré a CJ en GTA 5...', 'Fisper')] },
    other: { count: 339, videos: [card('fffffffffff', 'Ser vs Estar', 'Hoy Hablamos')] },
  },
  channels: [],
};

let fetchWithAuth = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>();

function respond(handler: (url: URL, init?: RequestInit) => unknown) {
  fetchWithAuth = vi.fn(async (url: string, init?: RequestInit) =>
    new Response(JSON.stringify(handler(new URL(url), init) ?? {}), { status: 200 }));
}

function homeElement(language = 'es') {
  return (
    <UserContext.Provider value={{
      user: { id: 'u', email: null, is_anonymous: false } as never,
      fetchWithAuth,
      loading: false,
      language: { code: language, name: language } as never,
      availableLanguages: [],
      setLanguage: () => {},
      initializeLanguage: async () => {},
    }}>
      <VideoHome />
    </UserContext.Provider>
  );
}

function renderHome() {
  return render(homeElement());
}

beforeEach(() => {
  extension.state = 'installed';
  respond((url) => (url.pathname === '/api/home' ? PAGE : { channel: 'Molaviajar' }));
});

afterEach(() => {
  sessionStorage.clear();
  localStorage.clear();
});

it('shows each video with its channel, length and how much is known', async () => {
  renderHome();
  const night = (await screen.findByText(NIGHT.title)).closest('li')!;
  expect(within(night).getByText('Katy Travels')).toBeTruthy();
  expect(within(night).getByText('22:28')).toBeTruthy();
  expect(night.textContent).toContain('96% · 14 new words');
  expect(screen.getByText('Ary Tenorio · watched 7 of 17 min')).toBeTruthy();
  expect(screen.getByRole('heading', { name: 'Channels at your level' })).toBeTruthy();
  expect(screen.getByText('96% known · 8 videos')).toBeTruthy();
  const topics = screen.getByRole('group', { name: 'Topics' });
  expect(within(topics).getAllByRole('button').map((b) => b.textContent)).toEqual([
    'All', 'Following', 'Gaming', 'Travel', 'Watched',
  ]);
});

it('takes a card away at once with Not interested, and brings it back with Undo', async () => {
  renderHome();
  const butler = (await screen.findByText(BUTLER.title)).closest('li')!;
  fireEvent.click(within(butler).getByRole('button', { name: 'More actions' }));
  fireEvent.click(within(butler).getByRole('menuitem', { name: 'Not interested' }));

  expect(screen.queryByText(BUTLER.title)).toBeNull();
  const pill = await screen.findByRole('status');
  expect(pill.textContent).toContain('Hidden.');
  const hide = fetchWithAuth.mock.calls.find(([url]) => String(url).endsWith('/api/home/hide'))!;
  expect(JSON.parse(String(hide[1]?.body))).toEqual({ language: 'es', video_id: BUTLER.id, channel: false });

  fireEvent.click(within(pill).getByRole('button', { name: 'Hide all from Molaviajar' }));
  expect((await screen.findByRole('status')).textContent).toContain('Videos from Molaviajar hidden.');
  fireEvent.click(within(screen.getByRole('status')).getByRole('button', { name: 'Undo' }));
  const unhide = fetchWithAuth.mock.calls.find(([url]) => String(url).endsWith('/api/home/unhide'))!;
  expect(JSON.parse(String(unhide[1]?.body))).toEqual({ language: 'es', video_id: BUTLER.id, channel: true });
});

it('says where a topic starts when the grammar filter leaves nothing', async () => {
  localStorage.setItem('langfour-home-grammar-es', 'A2');
  respond((url) => {
    if (url.pathname !== '/api/home') return {};
    return url.searchParams.get('grammar') === 'A2' ? EMPTY : PAGE;
  });
  renderHome();

  expect(await screen.findByRole('heading', { name: 'Videos start at B1' })).toBeTruthy();
  const levels = screen.getByRole('group', { name: 'Videos at each grammar level' });
  expect(within(levels).getByRole('button', { name: 'A2 0' })).toBeDisabled();
  expect(screen.getByText('Videos up to B1')).toBeTruthy();
  expect(screen.getByText('Other topics up to A2')).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: 'Show all 35' }));
  expect(await screen.findByText(NIGHT.title)).toBeTruthy();
  expect(localStorage.getItem('langfour-home-grammar-es')).toBe('B1');
});

it('says how many words were saved on YouTube on the way back', async () => {
  sessionStorage.setItem('langfour-home-away', JSON.stringify({
    videoId: NIGHT.id, title: NIGHT.title, leftAt: new Date(Date.now() - 60_000).toISOString(),
  }));
  respond((url) => {
    if (url.pathname === '/api/home/return') return { share: 0.4, saved: 6 };
    return PAGE;
  });
  renderHome();

  const pill = await screen.findByRole('status');
  expect(pill.textContent).toBe('You saved 6 words from En este lugar no existe la nocheSee them');
  expect(within(pill).getByRole('link', { name: 'See them' }).getAttribute('href')).toBe('/vocabulary');
  const back = fetchWithAuth.mock.calls.find(([url]) => String(url).includes('/api/home/return'))!;
  expect(new URL(back[0]).searchParams.get('video_id')).toBe(NIGHT.id);
  expect(sessionStorage.getItem('langfour-home-away')).toBeNull();
});

it('explains the extension once, on the first video opened without it', async () => {
  extension.state = 'missing';
  const matchMedia = vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList);
  renderHome();

  fireEvent.click(await screen.findByText(NIGHT.title));
  const dialog = screen.getByRole('dialog', { name: 'Watch it with Langfour on YouTube' });
  expect(dialog.textContent).toContain("The 14 words you don't know light up in the subtitles");
  expect(within(dialog).getByRole('link', { name: 'Add to Chrome' }).getAttribute('href')).toBe('/extension');

  fireEvent.click(within(dialog).getByRole('link', { name: 'Watch without it' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(JSON.parse(sessionStorage.getItem('langfour-home-away')!).videoId).toBe(NIGHT.id);

  fireEvent.click(screen.getByText(BUTLER.title));
  expect(screen.queryByRole('dialog')).toBeNull();
  matchMedia.mockRestore();
});

async function hideCard(title: string) {
  const card = (await screen.findAllByText(title))[0].closest('li')!;
  fireEvent.click(within(card).getByRole('button', { name: 'More actions' }));
  fireEvent.click(within(card).getByRole('menuitem', { name: 'Not interested' }));
}

it('hides a video from channel previews as well as the grid', async () => {
  respond(() => ({ ...PAGE, channels: [{ ...PAGE.channels[0], best: [BASURERO] }] }));
  renderHome();
  await hideCard(BASURERO.title);
  expect(screen.queryByText(BASURERO.title)).toBeNull();
});

it('hides videos from the empty-filter shelves', async () => {
  localStorage.setItem('langfour-home-grammar-es', 'A2');
  respond((url) => url.pathname === '/api/home' ? EMPTY : {});
  renderHome();
  const title = EMPTY.empty!.nearest!.videos[0].title;
  await hideCard(title);
  expect(screen.queryByText(title)).toBeNull();
});

it('only offers Undo after the hide has been persisted', async () => {
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  fetchWithAuth = vi.fn((url: string) => url.endsWith('/hide')
    ? pending : Promise.resolve(new Response(JSON.stringify(PAGE))));
  renderHome();
  await hideCard(BUTLER.title);
  expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull();
  finish(new Response(JSON.stringify({ channel: null })));
  expect(await screen.findByRole('button', { name: 'Undo' })).toBeTruthy();
});

it('restores the channel when hiding it fails', async () => {
  respond((url, init) => {
    if (url.pathname === '/api/home') return PAGE;
    if (init?.body && JSON.parse(String(init.body)).channel) throw new Error('Offline');
    return {};
  });
  renderHome();
  await hideCard(BASURERO.title);
  fireEvent.click(await screen.findByRole('button', { name: 'Hide all from Ary Tenorio' }));
  expect(await screen.findByText(PAGE.channels[0].best[0].title)).toBeTruthy();
});

it('keeps a video hidden when Undo fails', async () => {
  respond((url) => {
    if (url.pathname.endsWith('/unhide')) throw new Error('Offline');
    return url.pathname === '/api/home' ? PAGE : {};
  });
  renderHome();
  await hideCard(BUTLER.title);
  fireEvent.click(await screen.findByRole('button', { name: 'Undo' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not undo hiding');
  expect(screen.queryByText(BUTLER.title)).toBeNull();
});

it('reloads the recommendations after unmarking a watched video', async () => {
  let unmarked = false;
  respond((url) => {
    if (url.pathname === '/api/watch') return { videos: [{
      video_id: BUTLER.id, title: BUTLER.title, watched_at: '2026-11-03', source: 'desktop',
    }] };
    if (url.pathname === '/api/watch/unmark') { unmarked = true; return {}; }
    return { ...PAGE, videos: unmarked ? PAGE.videos : [NIGHT] };
  });
  renderHome();
  await screen.findByText(NIGHT.title);
  fireEvent.click(screen.getByRole('button', { name: 'Watched' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Unmark' }));
  await screen.findByText('No watched videos yet');
  fireEvent.click(screen.getByRole('button', { name: 'All' }));
  expect(await screen.findByText(BUTLER.title)).toBeTruthy();
});

it('clears the previous language’s cards, topic and optimistic hides on a language switch', async () => {
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  fetchWithAuth = vi.fn((url: string) => url.includes('language=de')
    ? pending : Promise.resolve(new Response(JSON.stringify(url.includes('/api/home?') ? PAGE : {}))));
  const { rerender } = renderHome();
  await hideCard(BUTLER.title);
  await screen.findByRole('button', { name: 'Undo' });
  fireEvent.click(screen.getByRole('button', { name: 'Travel' }));
  rerender(homeElement('de'));
  expect(screen.queryByText(NIGHT.title)).toBeNull();
  expect(screen.getByRole('button', { name: 'All' })).toHaveAttribute('aria-pressed', 'true');
  finish(new Response(JSON.stringify(PAGE)));
  expect(await screen.findByText(BUTLER.title)).toBeTruthy();
});
