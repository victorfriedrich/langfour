import { render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import MediaPage from './page';
import { listImportedMedia, type ImportedMediaSummary } from './api';
import type { ExtensionStatus } from '../hooks/useExtensionStatus';

const base = { series: null, season: null, episode: null, language: 'es', duration: null, transcriptionModel: null, timebase: null, importedAt: '2026-10-18T10:00:00Z' };
const library: ImportedMediaSummary[] = [
  { ...base, id: 'song', type: 'song', title: 'Canción de prueba', artist: 'Prueba', wordCount: 15 },
  { ...base, id: 'ep', type: 'series', title: 'Prueba', series: 'Netling Test', season: 1, episode: 3, duration: 3240 },
  { ...base, id: 'art', type: 'article', title: 'El tranvía vuelve', site: 'Diario de prueba', wordCount: 36 },
];

vi.mock('../components/ProtectedRoute', () => ({ default: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('./api', () => ({ listImportedMedia: vi.fn(async () => library) }));
let extension: ExtensionStatus = { state: 'checking' };
vi.mock('../hooks/useExtensionStatus', () => ({ useExtensionStatus: () => extension }));
vi.mock('@/context/UserContext', async () => {
  const { createContext } = await import('react');
  return { UserContext: createContext({ language: { code: 'es' }, fetchWithAuth: () => {} }) };
});

beforeEach(() => { extension = { state: 'checking' }; });
afterEach(() => { vi.restoreAllMocks(); });

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
  vi.mocked(listImportedMedia).mockResolvedValueOnce([]);
  render(<MediaPage />);
  expect(await screen.findByRole('link', { name: 'Get the extension' })).toHaveAttribute('href', '/extension');
  expect(screen.queryByText('Add to Library')).not.toBeInTheDocument();
});

it('explains the reader flow instead once the extension is installed', async () => {
  extension = { state: 'installed', version: '1.0.0', signedIn: true, email: null };
  vi.mocked(listImportedMedia).mockResolvedValueOnce([]);
  render(<MediaPage />);
  expect(await screen.findByText('Add to Library')).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'Get the extension' })).not.toBeInTheDocument();
});

it('names the reader button instead of the shortcut on a touch device', async () => {
  extension = { state: 'installed', version: '1.0.0', signedIn: true, email: null };
  vi.mocked(listImportedMedia).mockResolvedValueOnce([]);
  vi.spyOn(navigator, 'maxTouchPoints', 'get').mockReturnValue(5);
  render(<MediaPage />);
  expect(await screen.findByText('Read this page')).toBeInTheDocument();
  expect(screen.queryByLabelText(/Press/)).not.toBeInTheDocument();
});
