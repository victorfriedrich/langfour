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

let fetchWithAuth: ReturnType<typeof vi.fn>;

function respond(handler: (url: URL, init?: RequestInit) => unknown) {
  fetchWithAuth = vi.fn(async (url: string, init?: RequestInit) =>
    new Response(JSON.stringify(handler(new URL(url), init) ?? {}), { status: 200 }));
}

function renderHome() {
  return render(
    <UserContext.Provider value={{
      user: { id: 'u', email: null, is_anonymous: false } as never,
      fetchWithAuth,
      loading: false,
      language: { code: 'es', name: 'Spanish' } as never,
      availableLanguages: [],
      setLanguage: () => {},
      initializeLanguage: async () => {},
    }}>
      <VideoHome />
    </UserContext.Provider>,
  );
}

beforeEach(() => {
  extension.state = 'installed';
  respond((url) => (url.pathname === '/api/home' ? PAGE : {}));
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
  const pill = screen.getByRole('status');
  expect(pill.textContent).toContain('Hidden.');
  const hide = fetchWithAuth.mock.calls.find(([url]) => String(url).endsWith('/api/home/hide'))!;
  expect(JSON.parse(hide[1].body)).toEqual({ language: 'es', video_id: BUTLER.id, channel: false });

  fireEvent.click(within(pill).getByRole('button', { name: 'Hide all from Molaviajar' }));
  expect(screen.getByRole('status').textContent).toContain('Videos from Molaviajar hidden.');
  fireEvent.click(within(screen.getByRole('status')).getByRole('button', { name: 'Undo' }));
  const unhide = fetchWithAuth.mock.calls.find(([url]) => String(url).endsWith('/api/home/unhide'))!;
  expect(JSON.parse(unhide[1].body)).toEqual({ language: 'es', video_id: BUTLER.id, channel: true });
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
