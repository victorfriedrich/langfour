/* ------------------------------------------------------------------ *
 *  src/components/LearningWordsTable.tsx                             *
 * ------------------------------------------------------------------ *
 *  • Source-filter dropdown & search **right‑aligned** (ml‑auto).    *
 *  • Uses Filter icon; wider dropdown; no source column.             *
 * ------------------------------------------------------------------ */

import React, { useState, useEffect, useRef, useCallback, useContext } from 'react';
import { ArrowUp, ArrowDown, Check, ChevronDown, Filter, Download, Search, X } from 'lucide-react';
import { supabase } from '@/lib/supabaseclient';
import { UserContext } from '@/context/UserContext';

import { useGetSources } from '../hooks/useGetSources';
import { useGetLearningWords, LearningWord } from '../hooks/useLearningWords';
import { useSetUserwordsStatus } from '../hooks/useSetUserwordsStatus';
import { useOverdueWords } from '../hooks/useOverdueWords';
import { useStuckWords } from '../hooks/useStuckWords';
import { getDaysUntilReview } from '../utils/dateUtils';
import { STUCK_PARAM, STUCK_VALUE, evidence, preselected } from '../vocabulary/stuck';

/* coloured “days‑due” pill */
function getDuePill(due: string) {
  const l = due.toLowerCase();
  if (l === 'due today') return { label: 'Due today', color: 'text-rose-600' };
  const n = parseInt(due, 10);
  if (isNaN(n)) return { label: due, color: 'text-gray-400' };
  if (n < 0) return { label: 'Overdue', color: 'text-rose-600' };
  if (n === 0) return { label: 'Due today', color: 'text-rose-600' };
  if (n <= 3) return { label: due, color: 'text-amber-600' };
  return { label: due, color: 'text-gray-400' };
}

/* dropdown */
interface SourcesDropdownProps {
  sources: string[];
  current: string | null;
  onChange: (s: string | null) => void;
}
const SourcesDropdown: React.FC<SourcesDropdownProps> = ({ sources, current, onChange }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const opts = [{ value: null, label: 'All Sources' }, ...sources.map((s) => ({ value: s, label: s }))];

  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  const label = opts.find((o) => o.value === current)?.label ?? 'All Sources';

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} className="flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-sm text-gray-600 hover:bg-gray-100 hover:text-gray-900">
        <Filter size={16} />
        <span className="truncate max-w-40 lg:max-w-none">{label}</span>
        <ChevronDown size={14} className={`transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-80 bg-white rounded-md shadow-xl z-20 border border-gray-200 overflow-hidden">
          <div className="flex flex-col divide-y divide-gray-100 max-h-64 overflow-y-auto">
            {opts.map((o, idx) => (
              <button
                key={idx}
                className={`flex items-center justify-between w-full px-4 py-3 text-left transition-colors hover:bg-gray-50 ${current === o.value ? 'bg-gray-50 text-indigo-600 font-medium' : 'text-gray-700'}`}
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
              >
                <span className="truncate max-w-56">{o.label}</span>
                {current === o.value && <Check size={16} className="text-indigo-600" />}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

interface ExportDropdownProps {
  onSelect: (t: 'anki' | 'csv') => void;
}

const ExportDropdown: React.FC<ExportDropdownProps> = ({ onSelect }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-800"
        aria-label="Export"
      >
        <Download size={16} />
      </button>
      {open && (
        <div className="absolute right-0 mt-2 w-32 bg-white rounded-md shadow-xl z-20 border border-gray-200 overflow-hidden">
          <div className="flex flex-col divide-y divide-gray-100">
            <button
              className="px-4 py-2 text-left hover:bg-gray-50"
              onClick={() => {
                onSelect('anki');
                setOpen(false);
              }}
            >
              Anki
            </button>
            <button
              className="px-4 py-2 text-left hover:bg-gray-50"
              onClick={() => {
                onSelect('csv');
                setOpen(false);
              }}
            >
              CSV
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

/* main component */
interface LearningWordsTableProps {
  onMovedToKnown?: () => void;
  onSourceChange?: (s: string | null) => void;
  source?: string | null;
  /** Langfour's due dates; hidden when another system (RemNote) schedules. */
  showDue?: boolean;
  /** How far along each word is, from the progress data (word id -> stage). */
  stages?: Map<number, 'new' | 'learning' | 'learned'>;
  /** All learning words in the current language, for the header. */
  total?: number;
  /** Called once, when the first page has loaded (or failed). */
  onReady?: () => void;
}

// The marks of the legend above, so a row reads like the legend.
const STAGE_DOT = {
  learned: { className: 'bg-indigo-700', label: 'Learned' },
  learning: { className: 'bg-indigo-400', label: 'Learning' },
  new: { className: 'bg-gray-200', label: 'Not started' },
} as const;

const LearningWordsTable: React.FC<LearningWordsTableProps> = ({
  onMovedToKnown,
  onSourceChange,
  source = null,
  showDue = true,
  stages,
  total,
  onReady,
}) => {
  const searchRef = useRef<HTMLInputElement>(null);
  // "/" jumps to search, as in most tools people already know.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName);
      if (e.key === '/' && !typing) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  /* "Common words you never reviewed": a second tab, opened by its link */
  const { words: stuckWords, moveToKnown } = useStuckWords();
  const [view, setView] = useState<'all' | 'stuck'>('all');
  // Until the user changes it, the selection is every word not looked up.
  const [stuckPicked, setStuckPicked] = useState<number[] | null>(null);
  const stuckSelected = stuckPicked ?? (stuckWords ? preselected(stuckWords) : []);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get(STUCK_PARAM) === STUCK_VALUE) setView('stuck');
  }, []);
  const showStuck = view === 'stuck' && !!stuckWords;
  const toggleStuck = (id: number) =>
    setStuckPicked((prev) => {
      const picked = prev ?? preselected(stuckWords ?? []);
      return picked.includes(id) ? picked.filter((w) => w !== id) : [...picked, id];
    });
  /* source dropdown */
  const [sources, setSources] = useState<string[]>([]);
  const [sourceFilter, setSourceFilter] = useState<string | null>(source);
  const { getSources } = useGetSources();
  const { language } = useContext(UserContext);
  useEffect(() => {
    (async () => {
      try { setSources(await getSources()); } catch {/* ignore */}
    })();
  }, [getSources]);
  useEffect(() => {
    setSourceFilter(source);
  }, [source]);

  /* order */
  const [direction, setDirection] = useState<'ASC' | 'DESC'>('ASC');
  const toggleDirection = () => setDirection((p) => (p === 'ASC' ? 'DESC' : 'ASC'));

  /* search debounce */
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState<string | null>(null);
  useEffect(() => { const t = setTimeout(() => setDebounced(search.trim() || null), 500); return () => clearTimeout(t); }, [search]);

  /* pagination */
  const pageSize = 20;
  const [cursor, setCursor] = useState<number>(0);
  const [words, setWords] = useState<LearningWord[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const loadedWordIds = useRef<Set<number>>(new Set());

  useEffect(() => {
    loadedWordIds.current.clear();
    setCursor(0);
    setWords([]);
    setHasMore(true);
  }, [debounced, sourceFilter, direction]);

  const { learningWords: fetched, isLoading, error } = useGetLearningWords({
    orderDirection: direction,
    cursorWordId: cursor,
    searchTerm: debounced,
    pageSize,
    sourceFilter,
  });

  useEffect(() => {
    if (cursor === 0) {
      loadedWordIds.current = new Set(fetched.map((word) => word.word_id));
      setWords(fetched);
      setHasMore(fetched.length === pageSize);
      return;
    }

    const newWords = fetched.filter((word) => !loadedWordIds.current.has(word.word_id));
    newWords.forEach((word) => loadedWordIds.current.add(word.word_id));

    // A filtered RPC can return the final page again when its cursor no
    // longer advances. Do not append that page indefinitely.
    setHasMore(fetched.length === pageSize && newWords.length > 0);
    if (newWords.length > 0) {
      setWords((prev) => [...prev, ...newWords]);
    }
  }, [fetched, cursor]);

  const reported = useRef(false);
  useEffect(() => {
    if (!isLoading && cursor === 0 && !reported.current) {
      reported.current = true;
      onReady?.();
    }
  }, [isLoading, cursor, onReady]);

  /* selection */
  const [selectedWords, setSelectedWords] = useState<number[]>([]);
  const [lastSelectedIndex, setLastSelectedIndex] = useState<number | null>(null);
  const { updateUserwordsStatus } = useSetUserwordsStatus();

  const fetchAllLearningWords = async () => {
    if (!language?.name) return [] as LearningWord[];
    const { data, error } = await supabase.rpc('get_learning_words', {
      order_direction: direction,
      cursor_word_id: 0,
      search_term: debounced,
      page_size: 10000,
      language_filter: language.code,
      source_filter: sourceFilter,
    });
    if (error) {
      console.error('Export fetch error:', error);
      return [] as LearningWord[];
    }
    return (data as LearningWord[]) ?? [];
  };

  const { words: overdueWords } = useOverdueWords(0, {
    dueType: 'both',
    pageSize: 10000,
    source: sourceFilter ?? undefined,
  });

  const triggerDownload = (filename: string, content: string) => {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleExport = async (type: 'anki' | 'csv') => {
    if (type === 'csv') {
      const all = await fetchAllLearningWords();
      const lines = all.map((w) => `${w.word}\t${w.translation}`).join('\n');
      triggerDownload('words.csv', lines);
    } else {
      const lines = overdueWords
        .map((w: any) => {
          const days = getDaysUntilReview(w.next_review_due_at);
          return `${w.word_root}\t${w.translation}\t${days}`;
        })
        .join('\n');
      triggerDownload('anki.tsv', lines);
    }
  };

  const toggleWordSelection = (id: number) => {
    setSelectedWords((prev) =>
      prev.includes(id) ? prev.filter((wordId) => wordId !== id) : [...prev, id]
    );
  };

  const handleRowClick = (
    e: React.MouseEvent,
    index: number,
    wordId: number
  ) => {
    if (e.shiftKey && lastSelectedIndex !== null) {
      e.preventDefault();
      const rangeStart = Math.min(index, lastSelectedIndex);
      const rangeEnd = Math.max(index, lastSelectedIndex);
      const newSelected = words.slice(rangeStart, rangeEnd + 1).map((w) => w.word_id);
      setSelectedWords((prev) => {
        const isRemoving = prev.includes(wordId);
        if (isRemoving) {
          return prev.filter((id) => !newSelected.includes(id));
        }
        return Array.from(new Set([...prev, ...newSelected]));
      });
    } else {
      toggleWordSelection(wordId);
      setLastSelectedIndex(index);
    }
  };

  const handleMoveToKnown = async () => {
    try {
      await updateUserwordsStatus(selectedWords, 'known');
      setWords((prev) => prev.filter((w) => !selectedWords.includes(w.word_id)));
      setSelectedWords([]);
      onMovedToKnown?.();
    } catch (err) {
      console.error('Error updating userwords status:', err);
    }
  };

  const handleStuckToKnown = async () => {
    try {
      const moved = await moveToKnown(stuckSelected);
      setStuckPicked(stuckSelected.filter((id) => !moved.includes(id)));
      setWords((prev) => prev.filter((w) => !moved.includes(w.word_id)));
      if (moved.length === stuckWords?.length) setView('all');
      onMovedToKnown?.();
    } catch (err) {
      console.error('Error moving words to known:', err);
    }
  };

  const observer = useRef<IntersectionObserver | null>(null);
  const lastRowRef = useCallback((node: HTMLTableRowElement | null) => {
    if (isLoading) return;
    if (observer.current) observer.current.disconnect();
    observer.current = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && hasMore && fetched.length === pageSize) {
        const lastId = fetched[fetched.length - 1]?.word_id; if (lastId) setCursor(lastId);
      }
    });
    if (node) observer.current.observe(node);
  }, [isLoading, hasMore, fetched, pageSize]);

  /* render */
  return (
    // No scroll box of its own: the list continues the page under the progress.
    <section>
      {/* header */}
      <div className="flex flex-wrap items-center gap-3 pb-3">
        <h2 className="flex flex-wrap items-baseline gap-x-6 gap-y-1 font-semibold">
          <button
            onClick={() => setView('all')}
            className={showStuck ? 'text-gray-400 hover:text-gray-600' : 'text-gray-900'}
          >
            Your words
            {total !== undefined && <span className="ml-2 font-normal tabular-nums text-gray-400">{total.toLocaleString()}</span>}
          </button>
          {!!stuckWords?.length && (
            <button
              onClick={() => setView('stuck')}
              className={showStuck ? 'text-gray-900' : 'text-gray-400 hover:text-gray-600'}
            >
              Common words you never reviewed
              <span className="ml-2 font-normal tabular-nums text-gray-400">{stuckWords.length.toLocaleString()}</span>
            </button>
          )}
        </h2>

        {/* right‑aligned group; under the tabs when there are two, which leave it no room */}
        <div
          className={`ml-auto flex items-center gap-1 ${stuckWords?.length ? 'basis-full justify-end' : ''} ${
            showStuck ? 'hidden' : ''
          }`}
        >
          <button
            onClick={toggleDirection}
            className="rounded-lg p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-800"
            aria-label={direction === 'ASC' ? 'Oldest first' : 'Newest first'}
            title={direction === 'ASC' ? 'Oldest first' : 'Newest first'}
          >
            {direction === 'ASC' ? <ArrowUp size={16} /> : <ArrowDown size={16} />}
          </button>
          <ExportDropdown onSelect={handleExport} />
          <SourcesDropdown
            sources={sources}
            current={sourceFilter}
            onChange={(s) => {
              setSourceFilter(s);
              onSourceChange?.(s);
            }}
          />
          <label className="relative ml-2">
            <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              ref={searchRef}
              type="text"
              placeholder="Search"
              className="w-48 rounded-lg border border-gray-200 py-1.5 pl-8 pr-7 text-sm placeholder:text-gray-400 focus:border-gray-400 focus:outline-none"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            {!search && (
              <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded border border-gray-200 px-1 text-[10px] text-gray-400">/</kbd>
            )}
          </label>
        </div>
      </div>

      {showStuck && (
        <table className="w-full table-auto">
          <tbody className="divide-y divide-gray-100 text-sm">
            {stuckWords!.map((w) => (
              <tr key={w.word_id} className="cursor-pointer hover:bg-gray-50" onClick={() => toggleStuck(w.word_id)}>
                <td className="w-10 py-2.5 pl-1 pr-3">
                  <input
                    type="checkbox"
                    checked={stuckSelected.includes(w.word_id)}
                    onChange={() => toggleStuck(w.word_id)}
                    onClick={(e) => e.stopPropagation()}
                    className="form-checkbox block h-4 w-4 text-indigo-600"
                  />
                </td>
                <td className="whitespace-nowrap py-2.5 pr-4 font-medium text-gray-900">
                  <div className="sm:min-w-56">{w.word}</div>
                </td>
                <td className="w-full whitespace-nowrap py-2.5 text-gray-500">{w.translation}</td>
                <td className="whitespace-nowrap py-2.5 pr-1 text-right text-xs text-gray-400">{evidence(w)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* table */}
      <div className={showStuck ? 'hidden' : ''}>
        <table
          className="w-full table-auto"
          onMouseDown={(e) => e.shiftKey && e.preventDefault()}
        >
          <tbody className="divide-y divide-gray-100 text-sm">
            {words.map((w, i) => {
              const last = i === words.length - 1;
              const { label, color } = getDuePill(w.review_due);
              return (
                <tr
                  key={w.word_id}
                  ref={last ? lastRowRef : null}
                  className="group cursor-pointer hover:bg-gray-50"
                  onClick={(e) => handleRowClick(e, i, w.word_id)}
                >
                  <td className="w-10 py-2.5 pl-1 pr-3">
                    <input
                      type="checkbox"
                      checked={selectedWords.includes(w.word_id)}
                      onChange={(e) => handleRowClick(e as any, i, w.word_id)}
                      className={`form-checkbox block h-4 w-4 text-indigo-600 ${
                        selectedWords.length ? '' : 'opacity-0 group-hover:opacity-100'
                      }`}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </td>
                  <td className="whitespace-nowrap py-2.5 pr-4 font-medium text-gray-900">
                    {/* min-width on the cell itself isn't honoured everywhere; on a block inside it is */}
                    <div className="sm:min-w-56">
                      {stages?.has(w.word_id) && (
                        <span
                          className={`mr-2.5 inline-block h-1.5 w-1.5 -translate-y-px rounded-full ${STAGE_DOT[stages.get(w.word_id)!].className}`}
                          title={STAGE_DOT[stages.get(w.word_id)!].label}
                        />
                      )}
                      {w.word}
                    </div>
                  </td>
                  <td className="w-full whitespace-nowrap py-2.5 text-gray-500">{w.translation}</td>
                  {showDue && (
                    <td className={`whitespace-nowrap py-2.5 pr-1 text-right text-xs font-medium ${color}`}>{label}</td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>

        {isLoading && (
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
        {!isLoading && words.length === 0 && (
          <p className="py-10 text-center text-sm text-gray-500">{search ? `No words match “${search}”.` : 'No words yet.'}</p>
        )}
      </div>
      {/* Floating action bar while words are selected */}
      {showStuck && stuckSelected.length > 0 && (
        <div className="fixed bottom-6 left-1/2 z-30 flex -translate-x-1/2 items-center gap-1 rounded-full bg-gray-900 py-1.5 pl-4 pr-1.5 text-sm text-white shadow-lg">
          <span className="mr-2 tabular-nums">{stuckSelected.length} selected</span>
          <button className="rounded-full bg-white px-3 py-1 font-medium text-gray-900 hover:bg-gray-100" onClick={handleStuckToKnown}>
            Move to known
          </button>
          <button className="rounded-full p-1.5 text-gray-400 hover:text-white" onClick={() => setStuckPicked([])} aria-label="Clear selection">
            <X size={16} />
          </button>
        </div>
      )}
      {!showStuck && selectedWords.length > 0 && (
        <div className="fixed bottom-6 left-1/2 z-30 flex -translate-x-1/2 items-center gap-1 rounded-full bg-gray-900 py-1.5 pl-4 pr-1.5 text-sm text-white shadow-lg">
          <span className="mr-2 tabular-nums">{selectedWords.length} selected</span>
          <button className="rounded-full bg-white px-3 py-1 font-medium text-gray-900 hover:bg-gray-100" onClick={handleMoveToKnown}>
            I already know these
          </button>
          <button className="rounded-full p-1.5 text-gray-400 hover:text-white" onClick={() => setSelectedWords([])} aria-label="Clear selection">
            <X size={16} />
          </button>
        </div>
      )}
    </section>
  );
};

export default LearningWordsTable;
