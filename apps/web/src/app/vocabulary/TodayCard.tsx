'use client';

import { ArrowUpRight, Check, Play } from 'lucide-react';
import { useRemnoteReviewUrl, type ReviewProvider } from '../hooks/useReviewProvider';

interface TodayCardProps {
  provider: ReviewProvider;
  due: number;
  onStartReview: () => void;
  onContextReview: () => void;
}

const primary =
  'inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50';
const secondary =
  'inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50';

/** What to do today. The same card whoever schedules: only the action
 *  changes, from a review here to a hand-off to RemNote. */
export default function TodayCard({ provider, due, onStartReview, onContextReview }: TodayCardProps) {
  const inRemnote = provider === 'remnote';
  const remnoteUrl = useRemnoteReviewUrl();

  return (
    <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl bg-gray-50 px-5 py-4">
      {due > 0 ? (
        <div className="flex items-baseline gap-2.5">
          <span className="text-2xl font-semibold tabular-nums text-gray-900">{due.toLocaleString()}</span>
          <span className="text-gray-600">
            {due === 1 ? 'word' : 'words'} due today{inRemnote ? ' in RemNote' : ''}
          </span>
        </div>
      ) : (
        <div className="flex items-center gap-3">
          <span className="grid h-9 w-9 place-items-center rounded-full bg-emerald-50 text-emerald-600 ring-1 ring-emerald-200">
            <Check size={18} strokeWidth={2.5} />
          </span>
          <div>
            <p className="font-medium text-gray-900">All caught up</p>
            <p className="text-sm text-gray-500">New reviews show up here when they are due.</p>
          </div>
        </div>
      )}

      <div className="flex gap-2">
        {inRemnote ? (
          <a className={primary} href={remnoteUrl} target="_blank" rel="noreferrer">
            Open RemNote <ArrowUpRight size={16} />
          </a>
        ) : (
          <>
            <button className={secondary} onClick={onContextReview} disabled={due === 0}>
              Words in context
            </button>
            <button className={primary} onClick={onStartReview} disabled={due === 0}>
              <Play size={16} /> Start review
            </button>
          </>
        )}
      </div>
    </section>
  );
}
