import { render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { useReviewProvider } from '../hooks/useReviewProvider';
import TodayCard from './TodayCard';

const db = vi.hoisted(() => ({ from: vi.fn(), select: vi.fn(), eq: vi.fn(), maybeSingle: vi.fn() }));
vi.mock('@/lib/supabaseclient', () => ({ supabase: { from: db.from } }));
vi.mock('@/context/UserContext', async () => {
  const { createContext } = await import('react');
  return { UserContext: createContext({ user: { id: 'reader' } }) };
});

beforeEach(() => {
  vi.clearAllMocks();
  db.from.mockReturnValue(db);
  db.select.mockReturnValue(db);
  db.eq.mockReturnValue(db);
});

function PracticeActions() {
  const { provider, remnoteDocumentUrl } = useReviewProvider();
  return provider && <TodayCard provider={provider} remnoteDocumentUrl={remnoteDocumentUrl}
    due={2} onStartReview={() => {}} onContextReview={() => {}} />;
}

it('keeps all cards reachable alongside the document without a second settings request', async () => {
  db.maybeSingle.mockResolvedValue({ data: { review_provider: 'remnote', remnote_root_rem_id: 'doc_123' } });
  render(<PracticeActions />);
  expect(await screen.findByRole('link', { name: 'All RemNote cards' })).toHaveAttribute('href', 'https://www.remnote.com/flashcards');
  expect(screen.getByRole('link', { name: 'Langfour document' })).toHaveAttribute('href', 'https://www.remnote.com/flashcards/doc_123');
  expect(db.from).toHaveBeenCalledTimes(1);
  expect(db.select).toHaveBeenCalledWith('review_provider, remnote_root_rem_id');
});

it.each([null, '../../invalid'])('keeps all reviews reachable without a valid document (%s)', async (root) => {
  db.maybeSingle.mockResolvedValue({ data: { review_provider: 'remnote', remnote_root_rem_id: root } });
  render(<PracticeActions />);
  expect(await screen.findByRole('link', { name: 'All RemNote cards' })).toHaveAttribute('href', 'https://www.remnote.com/flashcards');
  expect(screen.queryByRole('link', { name: 'Langfour document' })).not.toBeInTheDocument();
});

it('uses Langfour reviews without loading separate document settings', async () => {
  db.maybeSingle.mockResolvedValue({ data: { review_provider: 'langfour', remnote_root_rem_id: 'old_doc' } });
  render(<PracticeActions />);
  expect(await screen.findByRole('button', { name: 'Start review' })).toBeEnabled();
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
  expect(db.from).toHaveBeenCalledTimes(1);
});
