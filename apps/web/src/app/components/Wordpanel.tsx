import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowDown, ArrowLeft, ArrowUp, Check, ChevronDown, ChevronUp, Loader2, X } from 'lucide-react';
import { useAddBucketWords, type BucketMove, type WordBucket } from '../hooks/useAddBucketWords';
import { useMissingWords } from '../hooks/useMissingWords';
import { useUpdateUserwords } from '../hooks/useUpdateUserwords';
import type { TranscriptChunk } from '../media/api';
import EmptyState from './EmptyState';
import MediaText from './MediaText';

interface WordpanelProps {
  videoId: string;
  videoTitle: string;
  onClose: (addedWordsCount: number) => void;
  variant?: 'panel' | 'page';
  /** The small label above the title on the full page, e.g. "Article vocabulary". */
  eyebrow?: string;
  /** Where the words come from: the shared video corpus, or the user's Library. */
  source?: 'videos' | 'media';
  transcript?: TranscriptChunk[];
}

interface MissingWord {
  id: number;
  content: string;
  translation: string;
  importance?: number | null;
  key?: boolean;
  bucket?: WordBucket;
  familiarity?: number | null;
}

const Wordpanel: React.FC<WordpanelProps> = ({ videoId, videoTitle, onClose, variant = 'panel', transcript = [], eyebrow = 'Episode vocabulary', source = 'videos' }) => {
  const [selectedWords, setSelectedWords] = useState<number[]>([]);
  const [isShiftPressed, setIsShiftPressed] = useState(false);
  const missing = useMissingWords(videoId, source);
  const { isLoading, error } = missing;
  // The text's most important words come first, most important on top. Beside
  // the text, the rest follow it: each word where it first appears.
  const firstSeen = useMemo(() => firstAppearance(transcript), [transcript]);
  const keyWords = useMemo(() => byImportance(missing.recommendedWords.filter((word) => word.key)), [missing.recommendedWords]);
  const recommendedWords = useMemo(() => inTextOrder(missing.recommendedWords.filter((word) => !word.key), firstSeen), [missing.recommendedWords, firstSeen]);
  const flaggedWords = useMemo(() => inTextOrder(missing.flaggedWords, firstSeen), [missing.flaggedWords, firstSeen]);
  const allWords = useMemo(() => [...keyWords, ...recommendedWords, ...flaggedWords], [keyWords, recommendedWords, flaggedWords]);
  const { addWordsToUserwords } = useUpdateUserwords();
  const addBucketWords = useAddBucketWords();
  // Accounts with the three groups: where the learner moved a word wins over
  // where Jev put it, including when the ratings arrive after the move.
  const [moved, setMoved] = useState<Map<number, WordBucket>>(new Map());
  const moveWord = useCallback((id: number, bucket: WordBucket) => {
    setMoved((current) => new Map(current).set(id, bucket));
  }, []);
  const groups = useMemo(() => {
    if (!missing.buckets) return null;
    const words: MissingWord[] = [...missing.recommendedWords, ...missing.flaggedWords];
    const inGroup = (bucket: WordBucket) => words.filter((word) => (moved.get(word.id) ?? word.bucket ?? 'skip') === bucket);
    return {
      probably: [...inGroup('probably')].sort((a, b) => (b.familiarity ?? 0) - (a.familiarity ?? 0)),
      should: byImportance(inGroup('should')),
      skip: inTextOrder(inGroup('skip'), firstSeen),
    };
  }, [missing.buckets, missing.recommendedWords, missing.flaggedWords, moved, firstSeen]);
  const fullPage = variant === 'page';
  // On the page, the text sits beside the list, laid out as the reader showed it.
  const showText = fullPage && transcript.length > 0;
  const newIds = useMemo(() => new Set(allWords.map((word) => word.id)), [allWords]);

  const toggleWordSelection = useCallback((wordId: number) => {
    setSelectedWords((current) => current.includes(wordId) ? current.filter((id) => id !== wordId) : [...current, wordId]);
  }, []);

  const handleWordClick = useCallback((event: React.MouseEvent, word: MissingWord, index: number) => {
    if (event.shiftKey && selectedWords.length > 0) {
      event.preventDefault();
      const lastSelectedIndex = allWords.findIndex((item) => item.id === selectedWords[selectedWords.length - 1]);
      const [start, end] = [Math.min(index, lastSelectedIndex), Math.max(index, lastSelectedIndex)];
      const range = allWords.slice(start, end + 1).map((item) => item.id);
      setSelectedWords((current) => Array.from(new Set([...current, ...range])));
    } else {
      toggleWordSelection(word.id);
    }
  }, [allWords, selectedWords, toggleWordSelection]);

  const toggleWordGroup = useCallback((group: MissingWord[]) => {
    const ids = group.map((word) => word.id);
    const allSelected = ids.every((id) => selectedWords.includes(id));
    setSelectedWords((current) => allSelected ? current.filter((id) => !ids.includes(id)) : Array.from(new Set([...current, ...ids])));
  }, [selectedWords]);

  const addToLearningSet = useCallback(async () => {
    try {
      await addWordsToUserwords(selectedWords, videoId);
      onClose(selectedWords.length);
    } catch {
      onClose(0);
    }
  }, [selectedWords, addWordsToUserwords, onClose, videoId]);

  const addGroups = useCallback(async () => {
    if (!groups) return;
    const familiar = groups.probably.map((word) => word.id);
    const priority = groups.should.map((word) => word.id);
    const moves: BucketMove[] = allWords.flatMap((word) => {
      const now = moved.get(word.id);
      const was = word.bucket ?? 'skip';
      return now && now !== was ? [{ word_id: word.id, was, now }] : [];
    });
    try {
      await addBucketWords({ familiar, priority, source: videoId, moves });
      onClose(familiar.length + priority.length);
    } catch {
      onClose(0);
    }
  }, [groups, allWords, moved, addBucketWords, videoId, onClose]);

  // Beside the text, the words that will be added are the marked ones.
  const addedIds = useMemo(() => groups ? [...groups.probably, ...groups.should].map((word) => word.id) : selectedWords, [groups, selectedWords]);
  const clickTextWord = useCallback((id: number) => {
    if (groups) moveWord(id, addedIds.includes(id) ? 'skip' : 'should');
    else toggleWordSelection(id);
  }, [groups, addedIds, moveWord, toggleWordSelection]);

  useEffect(() => {
    const updateShiftState = (event: KeyboardEvent) => setIsShiftPressed(event.shiftKey);
    window.addEventListener('keydown', updateShiftState);
    window.addEventListener('keyup', updateShiftState);
    return () => {
      window.removeEventListener('keydown', updateShiftState);
      window.removeEventListener('keyup', updateShiftState);
    };
  }, []);

  const shell = fullPage ? 'min-h-screen w-full bg-white' : 'fixed right-0 top-11 z-50 flex h-[calc(100dvh-48px)] w-full flex-col bg-white shadow-2xl md:top-0 md:h-full md:w-[420px]';

  // Loading and errors render inside the panel, so it slides in once instead of
  // a bare spinner appearing over the dimmed page first.
  if (isLoading || error) {
    return (
      <div className={shell} onClick={(event) => event.stopPropagation()}>
        {!fullPage && <Header videoTitle={videoTitle} eyebrow={eyebrow} wordCount={0} fullPage={false} onClose={onClose} />}
        {isLoading
          ? <div className={`flex flex-1 items-center justify-center ${fullPage ? 'min-h-[70vh]' : ''}`}><Loader2 className="h-6 w-6 animate-spin text-gray-400" /></div>
          : <p className={fullPage ? 'mx-auto max-w-3xl px-4 py-10 text-sm text-red-600 sm:px-8' : 'px-5 py-6 text-sm text-red-600'}>{error}</p>}
      </div>
    );
  }

  const list = allWords.length === 0 ? <NothingNew fullPage={fullPage} onClose={onClose} /> : groups ? <>
    <BucketGroup label="Words you probably know" words={groups.probably} actions={(word) => <ArrowButton label={`Move ${word.content} down`} onClick={() => moveWord(word.id, 'should')} icon={ArrowDown} />} />
    <BucketGroup label="Words you should know" words={groups.should} actions={(word) => <><ArrowButton label={`Move ${word.content} up`} onClick={() => moveWord(word.id, 'probably')} icon={ArrowUp} /><ArrowButton label={`Move ${word.content} down`} onClick={() => moveWord(word.id, 'skip')} icon={ArrowDown} /></>} />
    <BucketGroup label="Skip for now" words={groups.skip} actions={(word) => <><TextButton label={`Know ${word.content}`} text="Know" onClick={() => moveWord(word.id, 'probably')} /><TextButton label={`Priority ${word.content}`} text="Priority" onClick={() => moveWord(word.id, 'should')} /></>} />
  </> : <>
    {keyWords.length > 0 && <WordGroup label="Key words" words={keyWords} startIndex={0} selectedWords={selectedWords} toggleGroup={() => toggleWordGroup(keyWords)} handleWordClick={handleWordClick} toggleWordSelection={toggleWordSelection} />}
    {(recommendedWords.length > 0 || keyWords.length === 0) && <WordGroup label={keyWords.length > 0 ? 'Other words' : 'Recommended'} words={recommendedWords} startIndex={keyWords.length} selectedWords={selectedWords} toggleGroup={() => toggleWordGroup(recommendedWords)} handleWordClick={handleWordClick} toggleWordSelection={toggleWordSelection} />}
    {flaggedWords.length > 0 && <WordGroup label="Flagged" words={flaggedWords} startIndex={keyWords.length + recommendedWords.length} selectedWords={selectedWords} collapsible toggleGroup={() => toggleWordGroup(flaggedWords)} handleWordClick={handleWordClick} toggleWordSelection={toggleWordSelection} />}
  </>;
  const header = <Header videoTitle={videoTitle} eyebrow={eyebrow} wordCount={allWords.length} fullPage={fullPage} wide={showText} onClose={onClose} />;
  // Beside the text, the list is a column of its own: it starts level with the
  // page's top, stays put while the text scrolls and scrolls on its own,
  // down to the window's bottom edge.
  const body = !showText
    ? <>{header}<div className={fullPage ? 'mx-auto max-w-3xl flex-1 space-y-10 px-4 pb-32 sm:px-8' : 'flex-1 space-y-8 overflow-y-auto px-5 py-5'}>{list}</div></>
    : <div className="mx-auto max-w-[70rem] px-4 sm:px-8 lg:grid lg:grid-cols-[minmax(0,42rem)_20rem] lg:items-start lg:gap-16">
      <div className="pb-12 lg:pb-32">{header}<MediaText chunks={transcript} newIds={newIds} selectedIds={addedIds} onWordClick={clickTextWord} /></div>
      <aside className="space-y-10 pb-32 lg:sticky lg:top-0 lg:h-dvh lg:overflow-y-auto lg:pb-10 lg:pt-10">{list}</aside>
    </div>;

  return (
    <div className={`${shell} ${isShiftPressed ? 'select-none' : ''}`} onClick={(event) => event.stopPropagation()}>
      {body}
      {/* The page uses the app's floating selection pill; the panel has a bar, while there are words to add. */}
      {fullPage
        ? <SelectionPill count={addedIds.length} onAdd={groups ? addGroups : addToLearningSet} onClear={groups ? undefined : () => setSelectedWords([])} />
        : allWords.length > 0 && <ActionBar selectedWordsCount={addedIds.length} addToLearningSet={groups ? addGroups : addToLearningSet} />}
    </div>
  );
};

function Header({ videoTitle, eyebrow, wordCount, fullPage, wide = false, onClose }: { videoTitle: string; eyebrow: string; wordCount: number; fullPage: boolean; wide?: boolean; onClose: (count: number) => void }) {
  if (fullPage) {
    // Wide, it sits in the text's column, which already has the page gutter.
    return <header className={`${wide ? '' : 'mx-auto max-w-3xl px-4 sm:px-8'} pb-8 pt-10`}><button onClick={() => onClose(0)} className="mb-4 inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-900"><ArrowLeft size={16}/>Back to Media</button><h1 className="text-2xl font-semibold text-gray-900">{videoTitle}</h1><p className="mt-1 text-sm text-gray-500">{eyebrow}{wordCount > 0 && ` · ${wordCount} new ${wordCount === 1 ? 'word' : 'words'}`}</p></header>;
  }
  return <header className="flex items-start gap-3 border-b border-gray-100 px-5 py-4"><div className="min-w-0 flex-1"><h1 className="line-clamp-2 text-base font-semibold leading-6 text-gray-900">{videoTitle}</h1>{wordCount > 0 && <p className="mt-0.5 text-sm text-gray-500">{wordCount} new {wordCount === 1 ? 'word' : 'words'}</p>}</div><button onClick={() => onClose(0)} aria-label="Close" className="-mr-1.5 flex h-8 w-8 flex-none items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-800"><X size={18}/></button></header>;
}

/** Each word id's first place in the text, as [chunk, offset]. */
function firstAppearance(chunks: TranscriptChunk[]): Map<number, [number, number]> {
  const seen = new Map<number, [number, number]>();
  chunks.forEach((chunk, index) => {
    for (const [start, , id] of chunk.words ?? []) if (!seen.has(id)) seen.set(id, [index, start]);
  });
  return seen;
}

/** Most important first; words not ranked yet keep their order, after the rest. */
function byImportance(words: MissingWord[]): MissingWord[] {
  return [...words].sort((a, b) => (b.importance ?? 0) - (a.importance ?? 0));
}

/** Words in the order they first appear; any the text doesn't mark keep their order, after the rest.
 * Without the text (the side panel), most important first. */
function inTextOrder(words: MissingWord[], seen: Map<number, [number, number]>): MissingWord[] {
  if (seen.size === 0) return byImportance(words);
  const at = (word: MissingWord) => seen.get(word.id) ?? [Infinity, 0];
  return [...words].sort((a, b) => at(a)[0] - at(b)[0] || at(a)[1] - at(b)[1]);
}

// Every word is already in the learner's vocabulary (or there were none).
function NothingNew({ fullPage, onClose }: { fullPage: boolean; onClose: (count: number) => void }) {
  return <EmptyState icon={Check} title="Nothing new to learn here" actions={fullPage && <button onClick={() => onClose(0)} className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50"><ArrowLeft size={16}/>Back to Media</button>}>You already know every word in it.</EmptyState>;
}

function WordGroup({ label, words, startIndex, selectedWords, collapsible = false, toggleGroup, handleWordClick, toggleWordSelection }: { label: string; words: MissingWord[]; startIndex: number; selectedWords: number[]; collapsible?: boolean; toggleGroup: () => void; handleWordClick: (event: React.MouseEvent, word: MissingWord, index: number) => void; toggleWordSelection: (id: number) => void }) {
  const [expanded, setExpanded] = useState(!collapsible);
  const allSelected = words.length > 0 && words.every((word) => selectedWords.includes(word.id));
  return <section><div className="flex w-full items-center justify-between border-b border-gray-100 pb-2 text-sm"><button onClick={() => collapsible ? setExpanded((current) => !current) : undefined} className={`flex items-center gap-2 ${collapsible ? 'hover:text-indigo-700' : 'cursor-default'}`} aria-expanded={expanded}><span className="font-medium text-gray-900">{label}<span className="ml-1.5 tabular-nums text-gray-400">{words.length}</span></span>{collapsible && (expanded ? <ChevronUp size={16}/> : <ChevronDown size={16}/>)}</button>{expanded && <button onClick={toggleGroup} className="text-indigo-600 hover:text-indigo-700">{allSelected ? 'Clear all' : 'Select all'}</button>}</div>{/* Words and translations line up in columns, as on Vocabulary. */}{expanded && <ul className="grid grid-cols-[auto_fit-content(11rem)_minmax(0,1fr)] divide-y divide-gray-100">{words.map((word, index) => <WordItem key={word.id} word={word} index={startIndex + index} selected={selectedWords.includes(word.id)} handleWordClick={handleWordClick} toggleWordSelection={toggleWordSelection}/>)}</ul>}</section>;
}

function WordItem({ word, index, selected, handleWordClick, toggleWordSelection }: { word: MissingWord; index: number; selected: boolean; handleWordClick: (event: React.MouseEvent, word: MissingWord, index: number) => void; toggleWordSelection: (id: number) => void }) {
  const checkbox = <input type="checkbox" checked={selected} onChange={() => toggleWordSelection(word.id)} className="mt-0.5 h-4 w-4 shrink-0 text-indigo-600" onClick={(event) => event.stopPropagation()}/>;
  return <li className="col-span-3 grid cursor-pointer grid-cols-subgrid items-start gap-x-3 py-3 pl-1 text-sm hover:bg-gray-50" onClick={(event) => handleWordClick(event, word, index)}>{checkbox}<span className="min-w-0 font-medium text-gray-900">{word.content}</span><span className="min-w-0 text-gray-500">{word.translation || 'No translation'}</span></li>;
}

// The same pill the Vocabulary page shows for a selection.
function BucketGroup({ label, words, actions }: { label: string; words: MissingWord[]; actions: (word: MissingWord) => React.ReactNode }) {
  return <section aria-label={label}><div className="border-b border-gray-100 pb-2 text-sm"><span className="font-medium text-gray-900">{label}<span className="ml-1.5 tabular-nums text-gray-400">{words.length}</span></span></div><ul className="divide-y divide-gray-100">{words.map((word) => <li key={word.id} className="flex items-center gap-3 py-2.5 pl-1 text-sm"><div className="min-w-0 flex-1"><div className="font-medium text-gray-900">{word.content}</div><div className="text-gray-500">{word.translation || 'No translation'}</div></div><div className="flex flex-none items-center gap-1.5">{actions(word)}</div></li>)}</ul></section>;
}

function ArrowButton({ label, onClick, icon: Icon }: { label: string; onClick: () => void; icon: typeof ArrowUp }) {
  return <button type="button" onClick={onClick} aria-label={label} className="flex h-8 w-8 items-center justify-center rounded-md border border-gray-200 bg-white text-gray-600 hover:bg-gray-50 hover:text-gray-900"><Icon size={16} /></button>;
}

function TextButton({ label, text, onClick }: { label: string; text: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} aria-label={label} className="h-8 rounded-md border border-gray-200 bg-white px-2.5 text-xs font-medium text-gray-700 hover:bg-gray-50 hover:text-gray-900">{text}</button>;
}

function SelectionPill({ count, onAdd, onClear }: { count: number; onAdd: () => void; onClear?: () => void }) {
  if (count === 0) return null;
  return <div className="fixed bottom-6 left-1/2 z-30 flex -translate-x-1/2 items-center gap-1 rounded-full bg-gray-900 py-1.5 pl-4 pr-1.5 text-sm text-white shadow-lg"><span className="mr-2 tabular-nums">{count} selected</span><button className="rounded-full bg-white px-3 py-1 font-medium text-gray-900 hover:bg-gray-100" onClick={onAdd}>Add to learning set</button>{onClear && <button className="rounded-full p-1.5 text-gray-400 hover:text-white" onClick={onClear} aria-label="Clear selection"><X size={16}/></button>}</div>;
}

function ActionBar({ selectedWordsCount, addToLearningSet }: { selectedWordsCount: number; addToLearningSet: () => void }) {
  return <div className="border-t border-gray-100 px-5 py-4"><button onClick={addToLearningSet} disabled={selectedWordsCount === 0} className={`h-10 w-full rounded-lg text-sm font-medium transition ${selectedWordsCount > 0 ? 'bg-indigo-600 text-white hover:bg-indigo-700' : 'cursor-not-allowed bg-gray-100 text-gray-400'}`}>Add {selectedWordsCount} {selectedWordsCount === 1 ? 'word' : 'words'} to learning set</button></div>;
}

export default Wordpanel;
