import React, { useCallback, useContext, useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { supabase } from '@/lib/supabaseclient';
import { UserContext } from '@/context/UserContext';
import { useSetUserwordsStatus } from '../hooks/useSetUserwordsStatus';
import { KNEW_HINT, LEARNED_HINT } from '@/lib/knownWords';

interface KnownWord {
  word_id: number;
  word: string;
  translation: string | null;
  source: 'declared' | 'reviews';
}

const PAGE = 50;

/** The words Langfour counts as known (sql/known_words.sql): marked known, or
 *  learned in reviews. Only marked words can be sent back to practice; a
 *  learned word is already being practised and drops out of this list by
 *  itself if it is forgotten. */
const KnownWords: React.FC<{ searchTerm: string }> = ({ searchTerm }) => {
  const languageCode = useContext(UserContext).language?.code;
  const { updateUserwordsStatus } = useSetUserwordsStatus();
  const [words, setWords] = useState<KnownWord[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const cursor = useRef(0);
  // Each new search or language is a new generation; answers from an older
  // one are dropped, and one page loads at a time.
  const generation = useRef(0);
  const inFlight = useRef(false);

  const loadMore = useCallback(async () => {
    if (!languageCode || inFlight.current) return;
    const mine = generation.current;
    inFlight.current = true;
    setLoading(true);
    const { data, error: rpcError } = await supabase.rpc('get_known_words_page', {
      language_filter: languageCode,
      search_term: searchTerm || null,
      cursor_word_id: cursor.current,
      page_size: PAGE,
    });
    inFlight.current = false;
    if (mine !== generation.current) return;
    setLoading(false);
    if (rpcError) {
      setError(rpcError.message);
      return;
    }
    const page = (data ?? []) as KnownWord[];
    cursor.current = page.at(-1)?.word_id ?? cursor.current;
    setWords((prev) => [...prev, ...page]);
    setHasMore(page.length === PAGE);
  }, [languageCode, searchTerm]);

  // A new search or language starts from the top.
  useEffect(() => {
    generation.current += 1;
    inFlight.current = false;
    cursor.current = 0;
    setWords([]);
    setSelected([]);
    setHasMore(true);
    loadMore();
  }, [loadMore]);

  const observer = useRef<IntersectionObserver | null>(null);
  const lastRowRef = useCallback(
    (node: HTMLTableRowElement | null) => {
      observer.current?.disconnect();
      if (!node || loading || !hasMore) return;
      observer.current = new IntersectionObserver((entries) => entries[0].isIntersecting && loadMore());
      observer.current.observe(node);
    },
    [loading, hasMore, loadMore],
  );

  const practiseAgain = async () => {
    try {
      await updateUserwordsStatus(selected, 'learning');
      setWords((prev) => prev.filter((w) => !selected.includes(w.word_id)));
      setSelected([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not move the words back to practice');
    }
  };

  const toggle = (id: number) => setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  return (
    // No scroll box of its own: the list continues the page under the summary.
    <div>
      <table className="w-full table-auto">
        <tbody className="divide-y divide-gray-100 text-sm">
          {words.map((w, i) => {
            const declared = w.source === 'declared';
            return (
              <tr
                key={w.word_id}
                ref={i === words.length - 1 ? lastRowRef : null}
                className={`group ${declared ? 'cursor-pointer hover:bg-gray-50' : ''}`}
                onClick={() => declared && toggle(w.word_id)}
              >
                <td className="w-10 py-2.5 pl-1 pr-3">
                  {declared && (
                    <input
                      type="checkbox"
                      checked={selected.includes(w.word_id)}
                      onChange={() => toggle(w.word_id)}
                      onClick={(e) => e.stopPropagation()}
                      className={`h-4 w-4 text-indigo-600 ${selected.length ? '' : 'opacity-0 group-hover:opacity-100'}`}
                    />
                  )}
                </td>
                <td className="w-56 whitespace-nowrap py-2.5 pr-4 font-medium text-gray-900">
                  {/* The marks of the summary above. */}
                  <span
                    className={`mr-2.5 inline-block h-1.5 w-1.5 -translate-y-px rounded-full ${declared ? 'bg-gray-300' : 'bg-indigo-600'}`}
                    title={declared ? KNEW_HINT : LEARNED_HINT}
                  />
                  {w.word}
                </td>
                <td className="w-full whitespace-nowrap py-2.5 pr-1 text-gray-500">{w.translation}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {loading && (
        <div className="divide-y divide-gray-100" aria-label="Loading">
          {Array.from({ length: words.length ? 2 : 6 }, (_, i) => (
            <div key={i} className="flex items-center gap-6 py-3 pl-11">
              <span className="h-3 w-28 animate-pulse rounded bg-gray-100" />
              <span className="h-3 w-40 animate-pulse rounded bg-gray-100" />
            </div>
          ))}
        </div>
      )}
      {error && <p className="py-4 text-center text-sm text-red-500">{error}</p>}
      {!loading && words.length === 0 && (
        <p className="py-10 text-center text-sm text-gray-500">
          {searchTerm ? `No known words match “${searchTerm}”.` : 'No known words yet.'}
        </p>
      )}

      {selected.length > 0 && (
        <div className="fixed bottom-6 left-1/2 z-30 flex -translate-x-1/2 items-center gap-1 rounded-full bg-gray-900 py-1.5 pl-4 pr-1.5 text-sm text-white shadow-lg">
          <span className="mr-2 tabular-nums">{selected.length} selected</span>
          <button className="rounded-full bg-white px-3 py-1 font-medium text-gray-900 hover:bg-gray-100" onClick={practiseAgain}>
            Practise again
          </button>
          <button className="rounded-full p-1.5 text-gray-400 hover:text-white" onClick={() => setSelected([])} aria-label="Clear selection">
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
};

export default KnownWords;
