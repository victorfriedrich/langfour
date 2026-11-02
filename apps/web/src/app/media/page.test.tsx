import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import MediaPage from './page';
import { getLibrary, saveLayout, type ImportedMediaSummary } from './api';
import type { LayoutNode } from './tree';
import type { ExtensionStatus } from '../hooks/useExtensionStatus';

const base = { series: null, season: null, episode: null, language: 'es', duration: null, transcriptionModel: null, timebase: null, importedAt: '2026-10-18T10:00:00Z' };
const library: ImportedMediaSummary[] = [
  { ...base, id: 'song', type: 'song', title: 'Canción de prueba', artist: 'Prueba', wordCount: 15 },
  { ...base, id: 'ep', type: 'series', title: 'Prueba', series: 'Netling Test', season: 1, episode: 3, duration: 3240 },
  { ...base, id: 'art', type: 'article', title: 'El tranvía vuelve', site: 'Diario de prueba', wordCount: 36 },
];

vi.mock('../components/ProtectedRoute', () => ({ default: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('./api', () => ({ getLibrary: vi.fn(async () => ({ media: library, layout: [] })), saveLayout: vi.fn(async () => {}) }));
let extension: ExtensionStatus = { state: 'checking' };
vi.mock('../hooks/useExtensionStatus', () => ({ useExtensionStatus: () => extension }));
vi.mock('@/context/UserContext', async () => {
  const { createContext } = await import('react');
  return { UserContext: createContext({ language: { code: 'es' }, fetchWithAuth: () => {} }) };
});

beforeEach(() => { extension = { state: 'checking' }; });
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

it('lists each item by its own title, with where it is from underneath', async () => {
  render(<MediaPage />);
  const row = (title: string) => screen.findByRole('link', { name: `Open vocabulary for ${title}` });
  const song = await row('Canción de prueba');
  expect(song).toHaveTextContent('Canción de prueba');
  expect(within(song).getByText('Prueba · 1 min read')).toBeInTheDocument();
  expect(within(await row('Prueba')).getByText('Netling Test · S01 E03 · 54 min')).toBeInTheDocument();
  expect(within(await row('El tranvía vuelve')).getByText('Diario de prueba · 1 min read')).toBeInTheDocument();
});

it('makes getting the extension the main action when it is missing', async () => {
  extension = { state: 'missing' };
  vi.mocked(getLibrary).mockResolvedValueOnce({ media: [], layout: [] });
  render(<MediaPage />);
  expect(await screen.findByRole('link', { name: 'Get the extension' })).toHaveAttribute('href', '/extension');
  expect(screen.queryByText('Add to Library')).not.toBeInTheDocument();
});

it('explains the reader flow instead once the extension is installed', async () => {
  extension = { state: 'installed', version: '1.0.0', signedIn: true, email: null };
  vi.mocked(getLibrary).mockResolvedValueOnce({ media: [], layout: [] });
  render(<MediaPage />);
  expect(await screen.findByText('Add to Library')).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'Get the extension' })).not.toBeInTheDocument();
});

it('names the Safari menu item instead of the shortcut on an iPad reporting a Mac', async () => {
  extension = { state: 'installed', version: '1.0.0', signedIn: true, email: null };
  vi.mocked(getLibrary).mockResolvedValueOnce({ media: [], layout: [] });
  vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)');
  vi.spyOn(navigator, 'maxTouchPoints', 'get').mockReturnValue(5);
  render(<MediaPage />);
  expect(await screen.findByText('Langfour')).toBeInTheDocument();
  expect(screen.queryByLabelText(/Press/)).not.toBeInTheDocument();
});

it('keeps the shortcut on a touchscreen laptop', async () => {
  extension = { state: 'installed', version: '1.0.0', signedIn: true, email: null };
  vi.mocked(getLibrary).mockResolvedValueOnce({ media: [], layout: [] });
  vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue('Mozilla/5.0 (Windows NT 10.0; Win64; x64)');
  vi.spyOn(navigator, 'maxTouchPoints', 'get').mockReturnValue(10);
  render(<MediaPage />);
  expect(await screen.findByLabelText('Press Ctrl Shift Y')).toBeInTheDocument();
});

const songs: LayoutNode[] = [{ type: 'folder', id: 'f1', name: 'Songs', color: 'rose', open: true, children: [{ type: 'item', id: 'song' }] }];

it('shows the saved folders, with new imports at the top level', async () => {
  vi.mocked(getLibrary).mockResolvedValueOnce({ media: library, layout: songs });
  render(<MediaPage />);
  const folder = await screen.findByRole('button', { name: /^Songs/, expanded: true });
  expect(screen.getByText('1 item')).toBeInTheDocument();
  const links = screen.getAllByRole('link').map((link) => link.getAttribute('aria-label'));
  expect(links).toEqual(['Open vocabulary for Prueba', 'Open vocabulary for El tranvía vuelve', 'Open vocabulary for Canción de prueba']);
  fireEvent.click(folder);
  expect(screen.getByRole('button', { name: /^Songs/, expanded: false })).toBeInTheDocument();
});

it('moves an item into a folder from its menu and saves the layout', async () => {
  vi.mocked(getLibrary).mockResolvedValueOnce({ media: library, layout: songs });
  render(<MediaPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'Actions for El tranvía vuelve' }));
  vi.useFakeTimers();
  fireEvent.click(within(screen.getByRole('menu')).getByRole('menuitem', { name: 'Songs' }));
  await act(async () => { vi.runAllTimers(); });
  expect(saveLayout).toHaveBeenLastCalledWith(expect.anything(), 'es', [
    { type: 'item', id: 'ep' },
    { ...songs[0], children: [{ type: 'item', id: 'art' }, { type: 'item', id: 'song' }] },
  ]);
});

it('names a new folder in place', async () => {
  render(<MediaPage />);
  fireEvent.click(await screen.findByRole('button', { name: 'New folder' }));
  const name = screen.getByRole('textbox', { name: 'Folder name' });
  fireEvent.change(name, { target: { value: 'Podcasts' } });
  fireEvent.keyDown(name, { key: 'Enter' });
  expect(screen.getByRole('button', { name: /^Podcasts/, expanded: true })).toBeInTheDocument();
});
