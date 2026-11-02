'use client';

import { useState } from 'react';
import { addLabel, picks, recapStats, type Recap } from '../../../../extension/src/youtubeRecap';

const primary =
  'inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50';
const secondary =
  'inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50';

interface YoutubeRecapProps {
  recap: Recap;
  /** Resolves to the words the API added. */
  onAdd: (words: { word_id: number; video_id: string }[]) => Promise<string[]>;
  onClose: () => void;
}

/** "Yesterday on YouTube": what was watched, its new words in one row, and
 *  one button that adds them. Tapping a word leaves it out. */
export default function YoutubeRecap({ recap, onAdd, onClose }: YoutubeRecapProps) {
  const [left, setLeft] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [added, setAdded] = useState<number | null>(null);
  const count = recap.words.length - left.size;

  const toggle = (id: number) =>
    setLeft((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const add = async () => {
    setBusy(true);
    try {
      // The API's count: a word saved meanwhile elsewhere isn't added again.
      setAdded((await onAdd(picks(recap, left))).length);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label="Yesterday on YouTube">
      <h2 className="font-semibold text-gray-900">
        Yesterday on YouTube <span className="font-normal text-gray-400">{recapStats(recap)}</span>
      </h2>
      <p className="mt-3 border-y border-gray-100 py-3 text-gray-900">
        {recap.words.map((w, i) => (
          <span key={w.word_id}>
            {i > 0 && ', '}
            <button
              type="button"
              onClick={() => toggle(w.word_id)}
              disabled={added !== null}
              title={left.has(w.word_id) ? 'Keep' : 'Leave out'}
              className={`hover:underline hover:decoration-gray-300 disabled:no-underline ${left.has(w.word_id) ? 'text-gray-400' : ''}`}
            >
              {w.word}
            </button>
          </span>
        ))}
      </p>
      <div className="mt-4 flex gap-2">
        {added === null ? (
          <>
            <button className={primary} onClick={add} disabled={busy || count === 0}>
              {addLabel(count)}
            </button>
            <button className={secondary} onClick={onClose}>
              Not now
            </button>
          </>
        ) : (
          <p className="text-sm text-gray-500">Added {added} to reviews</p>
        )}
      </div>
    </section>
  );
}
