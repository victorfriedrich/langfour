import { render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { useReviewProvider } from '../hooks/useReviewProvider';
import TodayCard from './TodayCard';

const db = vi.hoisted(() => ({ from: vi.fn(), select: vi.fn(), eq: vi.fn(), maybeSingle: vi.fn() }));
vi.mock('@/lib/supabaseclient', () => ({ supabase: { from: db.from } }));
vi.mock('@/context/UserContext', async () => {
  const { createContext } = await import('react');
  return { UserContext: createContext({ user: { id: 'reader' }, language: { code: 'es' } }) };
});

beforeEach(() => {
  vi.clearAllMocks();
  db.from.mockReturnValue(db);
  db.select.mockReturnValue(db);
  db.eq.mockReturnValue(db);
});

function PracticeActions() {
  const { provider, remnoteUrl } = useReviewProvider();
  return provider && <TodayCard provider={provider} remnoteUrl={remnoteUrl}
    due={2} onStartReview={() => {}} onContextReview={() => {}} />;
}

it('opens the notes of the language being learned', async () => {
  db.maybeSingle.mockResolvedValue({ data: {
    review_provider: 'remnote', remnote_root_rem_id: 'doc_123', remnote_language_rem_ids: { es: 'spanish_1', it: 'italian_1' },
  } });
  render(<PracticeActions />);
  expect(await screen.findByRole('link', { name: /Review 2 due/ })).toHaveAttribute('href', 'https://www.remnote.com/document/spanish_1');
  expect(db.from).toHaveBeenCalledTimes(1);
  expect(db.select).toHaveBeenCalledWith('review_provider, remnote_root_rem_id, remnote_language_rem_ids');
});

it('opens the Langfour document when the language has none yet', async () => {
  db.maybeSingle.mockResolvedValue({ data: {
    review_provider: 'remnote', remnote_root_rem_id: 'doc_123', remnote_language_rem_ids: { it: 'italian_1', es: '../../invalid' },
  } });
  render(<PracticeActions />);
  expect(await screen.findByRole('link', { name: /Review 2 due/ })).toHaveAttribute('href', 'https://www.remnote.com/document/doc_123');
});

it.each([null, '../../invalid'])('opens RemNote before the plugin has reported a document (%s)', async (root) => {
  db.maybeSingle.mockResolvedValue({ data: { review_provider: 'remnote', remnote_root_rem_id: root, remnote_language_rem_ids: {} } });
  render(<PracticeActions />);
  expect(await screen.findByRole('link', { name: /Review 2 due/ })).toHaveAttribute('href', 'https://www.remnote.com/');
});

it('uses Langfour reviews without loading separate document settings', async () => {
  db.maybeSingle.mockResolvedValue({ data: { review_provider: 'langfour', remnote_root_rem_id: 'old_doc' } });
  render(<PracticeActions />);
  expect(await screen.findByRole('button', { name: /Review 2 due/ })).toBeEnabled();
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
  expect(db.from).toHaveBeenCalledTimes(1);
});
