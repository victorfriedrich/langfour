'use client';

import { ArrowUpRight, FileText, Play } from 'lucide-react';
import type { ReviewProvider } from '../hooks/useReviewProvider';

interface TodayCardProps {
  provider: ReviewProvider;
  remnoteDocumentUrl: string | null;
  due: number;
  onStartReview: () => void;
  onContextReview: () => void;
}

const primary =
  'inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50';
const secondary =
  'inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50';

/** Today's reviews, as the buttons beside the page title. The same whoever
 *  schedules: only the action changes, from a review here to a hand-off to
 *  RemNote. The due count lives on the primary button. */
export default function TodayCard({ provider, remnoteDocumentUrl, due, onStartReview, onContextReview }: TodayCardProps) {
  const reviewLabel = due > 0 ? `Review ${due.toLocaleString()} due` : 'All caught up';

  if (provider === 'remnote') {
    return (
      <div className="flex gap-2">
        {remnoteDocumentUrl && (
          <a
            className={`${secondary} px-2.5`}
            href={remnoteDocumentUrl}
            target="_blank"
            rel="noreferrer"
            aria-label="Langfour document"
            title="Langfour document in RemNote"
          >
            <FileText size={16} />
          </a>
        )}
        <a className={primary} href="https://www.remnote.com/flashcards" target="_blank" rel="noreferrer" title="All RemNote cards">
          {due > 0 ? reviewLabel : 'Open RemNote'} <ArrowUpRight size={16} />
        </a>
      </div>
    );
  }

  return (
    <div className="flex gap-2">
      <button className={secondary} onClick={onContextReview} disabled={due === 0}>
        Words in context
      </button>
      <button className={primary} onClick={onStartReview} disabled={due === 0}>
        {due > 0 && <Play size={14} />} {reviewLabel}
      </button>
    </div>
  );
}
