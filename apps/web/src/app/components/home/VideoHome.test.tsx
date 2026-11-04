import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { UserContext } from '@/context/UserContext';
import VideoHome from './VideoHome';
import { basisText } from './Sections';
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
    because: 'Marc Vilas',
  }],
  basis: { following: ['Marc Vilas'], watched: 10 },
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
  basis: null,
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
  expect(screen.getByText('96% known · 8 videos · like Marc Vilas')).toBeTruthy();
  expect(screen.getByText('Based on Marc Vilas, which you follow, and 10 videos you watched.')).toBeTruthy();
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
  expect(within(pill).getByRole('link', { name: 'See them' }).getAttribute('href')).toBe('/practice');
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

it('opens the side panel with a video’s words from Show words, and Escape closes it', async () => {
  renderHome();
  const butler = (await screen.findByText(BUTLER.title)).closest('li')!;
  fireEvent.click(within(butler).getByRole('button', { name: 'More actions' }));
  fireEvent.click(within(butler).getByRole('menuitem', { name: 'Show words' }));

  expect(await screen.findByRole('heading', { name: BUTLER.title })).toBeTruthy();
  await waitFor(() => expect(fetchWithAuth.mock.calls.some(([url]) =>
    String(url).endsWith(`/api/videos/${BUTLER.id}/missing-words`))).toBe(true));
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('heading', { name: BUTLER.title })).toBeNull();
});

it('says what Channels at your level rests on, or how to steer it', () => {
  expect(basisText({ following: [], watched: 0 })).toMatch(/^Picked by how much you’d understand\. To match them/);
  expect(basisText(null)).toMatch(/turn on YouTube history/);
  expect(basisText({ following: [], watched: 1 })).toBe('Based on 1 video you watched.');
  expect(basisText({ following: ['A', 'B'], watched: 0 })).toBe('Based on A and B, which you follow.');
  expect(basisText({ following: ['A', 'B', 'C', 'D', 'E'], watched: 3 }))
    .toBe('Based on A, B, and 3 more, which you follow, and 3 videos you watched.');
});

it('suggests channels on a topic too, under its name', async () => {
  respond(() => PAGE);
  renderHome();
  await screen.findByText(NIGHT.title);
  fireEvent.click(within(screen.getByRole('group', { name: 'Topics' })).getByRole('button', { name: 'Travel' }));
  expect(await screen.findByRole('heading', { name: 'Travel channels at your level' })).toBeTruthy();
});

const topicButton = (name: string) =>
  within(screen.getByRole('group', { name: 'Topics' })).getByRole('button', { name });

const homeRequests = () => fetchWithAuth.mock.calls
  .map(([url]) => new URL(url))
  .filter((url) => url.pathname === '/api/home');

it('shows a topic already seen at once, without asking again', async () => {
  respond((url) => (url.searchParams.get('topic') === 'Travel'
    ? { ...PAGE, videos: [BUTLER], channels: [] } : { ...PAGE, videos: [NIGHT], channels: [] }));
  renderHome();
  await screen.findByText(NIGHT.title);
  fireEvent.click(topicButton('Travel'));
  await screen.findByText(BUTLER.title);
  expect(homeRequests()).toHaveLength(2);

  fireEvent.click(topicButton('All'));
  // No await: it is there in the same render.
  expect(screen.getByText(NIGHT.title)).toBeTruthy();
  expect(homeRequests()).toHaveLength(2);
});

it('reads the learner once a visit, and fetches a topic on hover', async () => {
  respond((url) => (url.searchParams.get('topic') === 'Travel'
    ? { ...PAGE, videos: [BUTLER], channels: [] } : { ...PAGE, videos: [NIGHT], channels: [] }));
  renderHome();
  await screen.findByText(NIGHT.title);
  expect(homeRequests()[0].searchParams.get('reuse')).toBeNull();

  fireEvent.pointerEnter(topicButton('Travel'));
  await waitFor(() => expect(homeRequests()).toHaveLength(2));
  expect(homeRequests()[1].searchParams.get('topic')).toBe('Travel');
  expect(homeRequests()[1].searchParams.get('reuse')).toBe('1');
  // The hover's request is the click's: the page doesn't change until then.
  expect(screen.getByText(NIGHT.title)).toBeTruthy();

  await act(async () => {});
  fireEvent.click(topicButton('Travel'));
  expect(await screen.findByText(BUTLER.title)).toBeTruthy();
  expect(homeRequests()).toHaveLength(2);
});

it('starts over after a follow, and leaves the current page alone', async () => {
  respond((url) => (url.pathname === '/api/home'
    ? (url.searchParams.get('topic') === 'Travel' ? { ...PAGE, videos: [BUTLER] } : PAGE) : {}));
  renderHome();
  await screen.findByText(NIGHT.title);
  fireEvent.click(topicButton('Travel'));
  await screen.findByRole('heading', { name: 'Travel channels at your level' });
  fireEvent.click(screen.getByRole('button', { name: 'Follow' }));
  await screen.findByRole('button', { name: 'Following' });
  expect(homeRequests()).toHaveLength(2);

  fireEvent.click(topicButton('All'));
  await waitFor(() => expect(homeRequests()).toHaveLength(3));
  const after = homeRequests()[2];
  expect(after.searchParams.get('topic')).toBe('All');
  expect(after.searchParams.get('reuse')).toBeNull();
});

it('reveals more channels a few at a time, and starts over on another topic', async () => {
  const channels = Array.from({ length: 7 }, (_, i) => ({
    ...PAGE.channels[0], name: `Channel ${i}`, channel_id: null, best: [],
  }));
  respond(() => ({ ...PAGE, channels }));
  renderHome();
  await screen.findByText('Channel 2');
  expect(screen.queryByText('Channel 3')).toBeNull();

  const more = () => screen.queryByRole('button', { name: 'Show more channels' });
  fireEvent.click(more()!);
  expect(screen.getByText('Channel 5')).toBeTruthy();
  expect(screen.queryByText('Channel 6')).toBeNull();
  fireEvent.click(more()!);
  expect(screen.getByText('Channel 6')).toBeTruthy();
  expect(more()).toBeNull();

  fireEvent.click(topicButton('Travel'));
  await screen.findByRole('heading', { name: 'Travel channels at your level' });
  expect(screen.queryByText('Channel 3')).toBeNull();
  expect(more()).toBeTruthy();
});
