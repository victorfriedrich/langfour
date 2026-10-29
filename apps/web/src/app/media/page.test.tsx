import { render, screen, within } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import MediaPage from './page';
import type { ImportedMediaSummary } from './api';

const base = { series: null, season: null, episode: null, language: 'es', duration: null, transcriptionModel: null, timebase: null, importedAt: '2026-10-18T10:00:00Z' };
const library: ImportedMediaSummary[] = [
  { ...base, id: 'song', type: 'song', title: 'Canción de prueba', artist: 'Prueba', wordCount: 15 },
  { ...base, id: 'ep', type: 'series', title: 'Prueba', series: 'Netling Test', season: 1, episode: 3, duration: 3240 },
  { ...base, id: 'art', type: 'article', title: 'El tranvía vuelve', site: 'Diario de prueba', wordCount: 36 },
];

vi.mock('../components/ProtectedRoute', () => ({ default: ({ children }: { children: React.ReactNode }) => children }));
vi.mock('./api', () => ({ listImportedMedia: vi.fn(async () => library) }));
vi.mock('@/context/UserContext', async () => {
  const { createContext } = await import('react');
  return { UserContext: createContext({ language: { code: 'es' }, fetchWithAuth: () => {} }) };
});

it('leads songs and articles with their own title, and episodes with their series', async () => {
  render(<MediaPage />);
  const card = async (title: string) => (await screen.findByRole('link', { name: `Open vocabulary for ${title}` }));
  const song = await card('Canción de prueba');
  expect(within(song).getByRole('heading', { level: 2 })).toHaveTextContent('Canción de prueba');
  expect(within(song).getByRole('heading', { level: 3 })).toHaveTextContent('Prueba');
  const episode = await card('Prueba');
  expect(within(episode).getByRole('heading', { level: 2 })).toHaveTextContent('Netling Test');
  expect(within(episode).getByRole('heading', { level: 3 })).toHaveTextContent('Prueba');
  const article = await card('El tranvía vuelve');
  expect(within(article).getByRole('heading', { level: 2 })).toHaveTextContent('El tranvía vuelve');
  expect(within(article).getByRole('heading', { level: 3 })).toHaveTextContent('Diario de prueba');
});
