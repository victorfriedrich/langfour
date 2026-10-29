import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Check, ChevronDown, ChevronUp, Eye, Loader2, X } from 'lucide-react';
import { useMissingWords } from '../hooks/useMissingWords';
import { useUpdateUserwords } from '../hooks/useUpdateUserwords';
import { useSeenVideos } from '../hooks/useSeenVideos';
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
}

const Wordpanel: React.FC<WordpanelProps> = ({ videoId, videoTitle, onClose, variant = 'panel', transcript = [], eyebrow = 'Episode vocabulary', source = 'videos' }) => {
  const [selectedWords, setSelectedWords] = useState<number[]>([]);
  const [isShiftPressed, setIsShiftPressed] = useState(false);
  const { recommendedWords, flaggedWords, isLoading, error } = useMissingWords(videoId, source);
  const allWords = useMemo(() => [...recommendedWords, ...flaggedWords], [recommendedWords, flaggedWords]);
  const { addWordsToUserwords } = useUpdateUserwords();
  const { seenVideos, markVideoAsSeen } = useSeenVideos(0);
  const fullPage = variant === 'page';
  // On the page, the text sits beside the list, laid out as the reader showed it.
  const showText = fullPage && transcript.length > 0;
  const newIds = useMemo(() => new Set(allWords.map((word) => word.id)), [allWords]);

  const toggleVideoSeen = useCallback(async () => {
    await markVideoAsSeen(videoId);
  }, [videoId, markVideoAsSeen]);

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

  useEffect(() => {
    const updateShiftState = (event: KeyboardEvent) => setIsShiftPressed(event.shiftKey);
    window.addEventListener('keydown', updateShiftState);
    window.addEventListener('keyup', updateShiftState);
    return () => {
      window.removeEventListener('keydown', updateShiftState);
      window.removeEventListener('keyup', updateShiftState);
    };
  }, []);

  const shell = fullPage ? 'min-h-screen w-full bg-white' : 'fixed right-0 top-11 z-50 flex h-[calc(100dvh-48px)] w-full flex-col bg-white shadow-lg md:top-0 md:h-full md:w-1/3';

  // Loading and errors render inside the panel, so it slides in once instead of
  // a bare spinner appearing over the dimmed page first.
  if (isLoading || error) {
    return (
      <div className={shell} onClick={(event) => event.stopPropagation()}>
        {!fullPage && <Header videoTitle={videoTitle} eyebrow={eyebrow} wordCount={0} fullPage={false} onClose={onClose} />}
        {isLoading
          ? <div className={`flex flex-1 items-center justify-center ${fullPage ? 'min-h-[70vh]' : ''}`}><Loader2 className="h-6 w-6 animate-spin text-gray-400" /></div>
          : <p className={fullPage ? 'max-w-3xl px-4 py-10 text-sm text-red-600 sm:px-8' : 'mx-auto mt-8 max-w-xl rounded-xl border border-red-200 bg-red-50 p-5 text-center text-red-700'}>{error}</p>}
      </div>
    );
  }

  const list = allWords.length === 0 ? <NothingNew fullPage={fullPage} onClose={onClose} /> : <>
    <WordGroup label="Recommended" words={recommendedWords} startIndex={0} selectedWords={selectedWords} fullPage={fullPage} toggleGroup={() => toggleWordGroup(recommendedWords)} handleWordClick={handleWordClick} toggleWordSelection={toggleWordSelection} />
    {flaggedWords.length > 0 && <WordGroup label="Flagged" words={flaggedWords} startIndex={recommendedWords.length} selectedWords={selectedWords} fullPage={fullPage} collapsible toggleGroup={() => toggleWordGroup(flaggedWords)} handleWordClick={handleWordClick} toggleWordSelection={toggleWordSelection} />}
  </>;
  const body = !showText
    ? <div className={fullPage ? 'max-w-3xl flex-1 space-y-10 px-4 pb-32 sm:px-8' : 'flex-1 space-y-4 overflow-y-auto'}>{list}</div>
    : <div className="px-4 pb-32 sm:px-8 lg:grid lg:grid-cols-[minmax(0,42rem)_20rem] lg:items-start lg:gap-16">
      <MediaText chunks={transcript} newIds={newIds} selectedIds={selectedWords} onWordClick={toggleWordSelection} />
      <aside className="mt-12 space-y-10 lg:sticky lg:top-6 lg:mt-0 lg:max-h-[calc(100vh-3rem)] lg:overflow-y-auto">{list}</aside>
    </div>;

  return (
    <div className={`${shell} ${isShiftPressed ? 'select-none' : ''}`} onClick={(event) => event.stopPropagation()}>
      <Header videoTitle={videoTitle} eyebrow={eyebrow} wordCount={allWords.length} fullPage={fullPage} wide={showText} onClose={onClose} />
      {body}
      {/* The page uses the app's floating selection pill; the panel keeps its bar for the Seen button. */}
      {fullPage
        ? <SelectionPill count={selectedWords.length} onAdd={addToLearningSet} onClear={() => setSelectedWords([])} />
        : <ActionBar isVideoSeen={seenVideos.includes(videoId)} selectedWordsCount={selectedWords.length} toggleVideoSeen={toggleVideoSeen} addToLearningSet={addToLearningSet} />}
    </div>
  );
};

function Header({ videoTitle, eyebrow, wordCount, fullPage, wide = false, onClose }: { videoTitle: string; eyebrow: string; wordCount: number; fullPage: boolean; wide?: boolean; onClose: (count: number) => void }) {
  if (fullPage) {
    return <header className={`${wide ? 'max-w-[42rem]' : 'max-w-3xl'} px-4 pb-8 pt-10 sm:px-8`}><button onClick={() => onClose(0)} className="mb-4 inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-900"><ArrowLeft size={16}/>Back to Media</button><h1 className="text-2xl font-semibold text-gray-900">{videoTitle}</h1><p className="mt-1 text-sm text-gray-500">{eyebrow}{wordCount > 0 && ` · ${wordCount} new ${wordCount === 1 ? 'word' : 'words'}`}</p></header>;
  }
  return <header className="border-b p-4"><div className="flex items-center justify-between"><button onClick={() => onClose(0)} aria-label="Close" className="order-2 text-gray-500 hover:text-gray-700"><X size={24}/></button><div className="min-w-0 flex-1"><h1 className="text-lg font-semibold">{videoTitle}</h1></div></div></header>;
}

// Every word is already in the learner's vocabulary (or there were none).
function NothingNew({ fullPage, onClose }: { fullPage: boolean; onClose: (count: number) => void }) {
  return <EmptyState icon={Check} title="Nothing new to learn here" actions={fullPage && <button onClick={() => onClose(0)} className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50"><ArrowLeft size={16}/>Back to Media</button>}>You already know every word in it.</EmptyState>;
}

function WordGroup({ label, words, startIndex, selectedWords, fullPage, collapsible = false, toggleGroup, handleWordClick, toggleWordSelection }: { label: string; words: MissingWord[]; startIndex: number; selectedWords: number[]; fullPage: boolean; collapsible?: boolean; toggleGroup: () => void; handleWordClick: (event: React.MouseEvent, word: MissingWord, index: number) => void; toggleWordSelection: (id: number) => void }) {
  const [expanded, setExpanded] = useState(!collapsible);
  const allSelected = words.length > 0 && words.every((word) => selectedWords.includes(word.id));
  return <section><div className={fullPage ? 'flex w-full items-center justify-between border-b border-gray-100 pb-2 text-sm' : 'flex w-full items-center justify-between border-b bg-gray-50 px-4 py-2 text-sm'}><button onClick={() => collapsible ? setExpanded((current) => !current) : undefined} className={`flex items-center gap-2 ${collapsible ? 'hover:text-indigo-700' : 'cursor-default'}`} aria-expanded={expanded}>{fullPage ? <span className="font-medium text-gray-900">{label}<span className="ml-1.5 tabular-nums text-gray-400">{words.length}</span></span> : <span className="font-medium">Select {label} ({words.length})</span>}{collapsible && (expanded ? <ChevronUp size={16}/> : <ChevronDown size={16}/>)}</button>{expanded && <button onClick={toggleGroup} className={fullPage ? 'text-indigo-600 hover:text-indigo-700' : 'font-semibold text-indigo-600'}>{allSelected ? 'Clear all' : 'Select all'}</button>}</div>{expanded && <ul className={fullPage ? 'divide-y divide-gray-100' : 'space-y-2 p-4'}>{words.map((word, index) => <WordItem key={word.id} word={word} index={startIndex + index} selected={selectedWords.includes(word.id)} fullPage={fullPage} handleWordClick={handleWordClick} toggleWordSelection={toggleWordSelection}/>)}</ul>}</section>;
}

function WordItem({ word, index, selected, fullPage, handleWordClick, toggleWordSelection }: { word: MissingWord; index: number; selected: boolean; fullPage: boolean; handleWordClick: (event: React.MouseEvent, word: MissingWord, index: number) => void; toggleWordSelection: (id: number) => void }) {
  const checkbox = <input type="checkbox" checked={selected} onChange={() => toggleWordSelection(word.id)} className={fullPage ? 'mt-0.5 h-4 w-4 shrink-0 text-indigo-600' : 'form-checkbox ml-3 h-5 w-5 text-indigo-600'} onClick={(event) => event.stopPropagation()}/>;
  if (fullPage) {
    return <li className="flex cursor-pointer items-start gap-3 py-3 pl-1 text-sm hover:bg-gray-50" onClick={(event) => handleWordClick(event, word, index)}>{checkbox}<p className="min-w-0"><span className="font-medium text-gray-900">{word.content}</span><span className="ml-3 text-gray-500">{word.translation || 'No translation'}</span></p></li>;
  }
  return <li className="flex cursor-pointer items-center justify-between border-b pb-2" onClick={(event) => handleWordClick(event, word, index)}><div className="flex min-w-0 flex-col"><span className="font-medium">{word.content}</span><span className="truncate text-sm text-slate-500">{word.translation || 'No translation'}</span></div>{checkbox}</li>;
}

// The same pill the Vocabulary page shows for a selection.
function SelectionPill({ count, onAdd, onClear }: { count: number; onAdd: () => void; onClear: () => void }) {
  if (count === 0) return null;
  return <div className="fixed bottom-6 left-1/2 z-30 flex -translate-x-1/2 items-center gap-1 rounded-full bg-gray-900 py-1.5 pl-4 pr-1.5 text-sm text-white shadow-lg"><span className="mr-2 tabular-nums">{count} selected</span><button className="rounded-full bg-white px-3 py-1 font-medium text-gray-900 hover:bg-gray-100" onClick={onAdd}>Add to learning set</button><button className="rounded-full p-1.5 text-gray-400 hover:text-white" onClick={onClear} aria-label="Clear selection"><X size={16}/></button></div>;
}

function ActionBar({ isVideoSeen, selectedWordsCount, toggleVideoSeen, addToLearningSet }: { isVideoSeen: boolean; selectedWordsCount: number; toggleVideoSeen: () => void; addToLearningSet: () => void }) {
  return <div className="flex items-center gap-2 border-t p-4"><button onClick={toggleVideoSeen} className={`flex items-center justify-center rounded-lg px-4 py-2.5 font-semibold transition ${isVideoSeen ? 'bg-slate-900 text-white' : 'bg-slate-200 text-slate-700 hover:bg-slate-300'}`}><Eye size={19} className="mr-2"/>Seen</button><button onClick={addToLearningSet} disabled={selectedWordsCount === 0} className={`flex-grow rounded-lg px-5 py-2.5 font-semibold transition ${selectedWordsCount > 0 ? 'bg-indigo-600 text-white shadow-sm hover:bg-indigo-700' : 'cursor-not-allowed bg-slate-200 text-slate-400'}`}>Add {selectedWordsCount} {selectedWordsCount === 1 ? 'word' : 'words'} to learning set</button></div>;
}

export default Wordpanel;
