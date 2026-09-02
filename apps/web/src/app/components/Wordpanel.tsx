import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Check, ChevronDown, ChevronUp, Eye, Loader2, X } from 'lucide-react';
import { useMissingWords } from '../hooks/useMissingWords';
import { useUpdateUserwords } from '../hooks/useUpdateUserwords';
import { useSeenVideos } from '../hooks/useSeenVideos';
import type { TranscriptChunk } from '../media/api';

interface WordpanelProps {
  videoId: string;
  videoTitle: string;
  onClose: (addedWordsCount: number) => void;
  variant?: 'panel' | 'page';
  transcript?: TranscriptChunk[];
}

interface MissingWord {
  id: number;
  content: string;
  translation: string;
}

const Wordpanel: React.FC<WordpanelProps> = ({ videoId, videoTitle, onClose, variant = 'panel', transcript = [] }) => {
  const [selectedWords, setSelectedWords] = useState<number[]>([]);
  const [isShiftPressed, setIsShiftPressed] = useState(false);
  const { recommendedWords, flaggedWords, isLoading, error } = useMissingWords(videoId);
  const allWords = useMemo(() => [...recommendedWords, ...flaggedWords], [recommendedWords, flaggedWords]);
  const { addWordsToUserwords } = useUpdateUserwords();
  const { seenVideos, markVideoAsSeen } = useSeenVideos(0);
  const fullPage = variant === 'page';

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

  if (isLoading) {
    return <div className={`flex items-center justify-center ${fullPage ? 'min-h-[70vh]' : 'h-40'}`}><Loader2 className="h-7 w-7 animate-spin text-indigo-500" /></div>;
  }

  if (error) {
    return <div className="mx-auto mt-8 max-w-xl rounded-xl border border-red-200 bg-red-50 p-5 text-center text-red-700">{error}</div>;
  }

  return (
    <div className={`${fullPage ? 'min-h-full w-full bg-slate-50' : 'fixed right-0 top-11 z-50 flex h-[calc(100dvh-48px)] w-full flex-col bg-white shadow-lg md:top-0 md:h-full md:w-1/3'} ${isShiftPressed ? 'select-none' : ''}`} onClick={(event) => event.stopPropagation()}>
      <Header videoTitle={videoTitle} wordCount={allWords.length} fullPage={fullPage} onClose={onClose} />
      <div className={fullPage ? 'mx-auto w-full max-w-6xl flex-1 space-y-8 px-5 py-8 pb-32' : 'flex-1 space-y-4 overflow-y-auto'}>
        <WordGroup label="Recommended" words={recommendedWords} startIndex={0} selectedWords={selectedWords} fullPage={fullPage} transcript={transcript} toggleGroup={() => toggleWordGroup(recommendedWords)} handleWordClick={handleWordClick} toggleWordSelection={toggleWordSelection} />
        {flaggedWords.length > 0 && <WordGroup label="Flagged" words={flaggedWords} startIndex={recommendedWords.length} selectedWords={selectedWords} fullPage={fullPage} transcript={transcript} collapsible toggleGroup={() => toggleWordGroup(flaggedWords)} handleWordClick={handleWordClick} toggleWordSelection={toggleWordSelection} />}
      </div>
      <ActionBar isVideoSeen={seenVideos.includes(videoId)} selectedWordsCount={selectedWords.length} fullPage={fullPage} toggleVideoSeen={toggleVideoSeen} addToLearningSet={addToLearningSet} />
    </div>
  );
};

function Header({ videoTitle, wordCount, fullPage, onClose }: { videoTitle: string; wordCount: number; fullPage: boolean; onClose: (count: number) => void }) {
  return <header className={fullPage ? 'border-b border-slate-200 bg-white' : 'border-b p-4'}><div className={fullPage ? 'mx-auto max-w-6xl px-5 py-8' : 'flex items-center justify-between'}><button onClick={() => onClose(0)} aria-label={fullPage ? 'Back to media' : 'Close'} className={fullPage ? 'mb-5 inline-flex items-center gap-2 rounded-lg text-sm font-semibold text-slate-600 transition hover:text-indigo-700' : 'order-2 text-gray-500 hover:text-gray-700'}>{fullPage ? <><ArrowLeft size={18}/><span>Back to media</span></> : <X size={24}/>}</button><div className="min-w-0 flex-1">{fullPage && <p className="mb-1 text-xs font-bold uppercase tracking-[0.2em] text-indigo-600">Episode vocabulary</p>}<h1 className={fullPage ? 'truncate text-3xl font-bold tracking-tight text-slate-950' : 'text-lg font-semibold'}>{videoTitle}</h1>{fullPage && <p className="mt-2 text-sm text-slate-500">Choose the words you want to learn. {wordCount} new {wordCount === 1 ? 'word' : 'words'} found.</p>}</div></div></header>;
}

function WordGroup({ label, words, startIndex, selectedWords, fullPage, transcript, collapsible = false, toggleGroup, handleWordClick, toggleWordSelection }: { label: string; words: MissingWord[]; startIndex: number; selectedWords: number[]; fullPage: boolean; transcript: TranscriptChunk[]; collapsible?: boolean; toggleGroup: () => void; handleWordClick: (event: React.MouseEvent, word: MissingWord, index: number) => void; toggleWordSelection: (id: number) => void }) {
  const [expanded, setExpanded] = useState(!collapsible);
  const allSelected = words.length > 0 && words.every((word) => selectedWords.includes(word.id));
  return <section><div className={fullPage ? 'mb-4 flex w-full items-center justify-between border-b border-slate-200 pb-3 text-sm' : 'flex w-full items-center justify-between border-b bg-gray-50 px-4 py-2 text-sm'}><button onClick={() => collapsible ? setExpanded((current) => !current) : undefined} className={`flex items-center gap-2 ${collapsible ? 'hover:text-indigo-700' : 'cursor-default'}`} aria-expanded={expanded}><span className={fullPage ? 'font-bold uppercase tracking-widest text-slate-600' : 'font-medium'}>{fullPage ? label : `Select ${label}`} ({words.length})</span>{collapsible && (expanded ? <ChevronUp size={17}/> : <ChevronDown size={17}/>)}</button>{expanded && <button onClick={toggleGroup} className="font-semibold text-indigo-600">{allSelected ? 'Clear all' : 'Select all'}</button>}</div>{expanded && <ul className={fullPage ? 'grid gap-3 sm:grid-cols-2 lg:grid-cols-3' : 'space-y-2 p-4'}>{words.map((word, index) => <WordItem key={word.id} word={word} index={startIndex + index} selected={selectedWords.includes(word.id)} fullPage={fullPage} sentences={findSentences(transcript, word.content)} handleWordClick={handleWordClick} toggleWordSelection={toggleWordSelection}/>)}</ul>}</section>;
}

function WordItem({ word, index, selected, fullPage, sentences, handleWordClick, toggleWordSelection }: { word: MissingWord; index: number; selected: boolean; fullPage: boolean; sentences: string[]; handleWordClick: (event: React.MouseEvent, word: MissingWord, index: number) => void; toggleWordSelection: (id: number) => void }) {
  return <li className={fullPage ? `group flex min-h-24 cursor-pointer items-start justify-between rounded-2xl border p-5 shadow-sm transition ${selected ? 'border-indigo-400 bg-indigo-50 ring-1 ring-indigo-200' : 'border-slate-200 bg-white hover:-translate-y-0.5 hover:border-indigo-200 hover:shadow-md'}` : 'flex cursor-pointer items-center justify-between border-b pb-2'} onClick={(event) => handleWordClick(event, word, index)}><div className="flex min-w-0 flex-col"><span className={fullPage ? 'truncate text-lg font-semibold text-slate-900' : 'font-medium'}>{word.content}</span><span className="truncate text-sm text-slate-500">{word.translation || 'No translation'}</span>{fullPage && sentences.map((sentence) => <span key={sentence} className="mt-3 text-sm leading-5 text-slate-600">“{sentence}”</span>)}</div>{fullPage ? <span className={`ml-3 mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border transition ${selected ? 'border-indigo-600 bg-indigo-600 text-white' : 'border-slate-300 bg-white group-hover:border-indigo-400'}`}>{selected && <Check size={15} strokeWidth={3}/>}</span> : <input type="checkbox" checked={selected} onChange={() => toggleWordSelection(word.id)} className="form-checkbox ml-3 h-5 w-5 text-indigo-600" onClick={(event) => event.stopPropagation()}/>}</li>;
}

function findSentences(transcript: TranscriptChunk[], word: string): string[] {
  const escapedWord = word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const wordPattern = new RegExp(`(^|[^\\p{L}\\p{N}])${escapedWord}(?=$|[^\\p{L}\\p{N}])`, 'iu');
  return transcript.flatMap((chunk) => chunk.text.match(/[^.!?]+[.!?]+|[^.!?]+$/g) || []).map((sentence) => sentence.trim()).filter((sentence) => wordPattern.test(sentence)).filter((sentence, index, matches) => matches.indexOf(sentence) === index).slice(0, 2);
}

function ActionBar({ isVideoSeen, selectedWordsCount, fullPage, toggleVideoSeen, addToLearningSet }: { isVideoSeen: boolean; selectedWordsCount: number; fullPage: boolean; toggleVideoSeen: () => void; addToLearningSet: () => void }) {
  return <div className={fullPage ? 'sticky bottom-0 border-t border-slate-200 bg-white/95 px-5 py-4 shadow-[0_-8px_30px_rgba(15,23,42,0.06)] backdrop-blur' : 'flex items-center space-x-2 border-t p-4'}><div className={fullPage ? 'mx-auto flex max-w-6xl items-center justify-end gap-3' : 'contents'}>{!fullPage && <button onClick={toggleVideoSeen} className={`flex items-center justify-center rounded-lg px-4 py-2.5 font-semibold transition ${isVideoSeen ? 'bg-slate-900 text-white' : 'bg-slate-200 text-slate-700 hover:bg-slate-300'}`}><Eye size={19} className="mr-2"/>Seen</button>}<button onClick={addToLearningSet} disabled={selectedWordsCount === 0} className={`${fullPage ? 'min-w-64' : 'flex-grow'} rounded-lg px-5 py-2.5 font-semibold transition ${selectedWordsCount > 0 ? 'bg-indigo-600 text-white shadow-sm hover:bg-indigo-700' : 'cursor-not-allowed bg-slate-200 text-slate-400'}`}>Add {selectedWordsCount} {selectedWordsCount === 1 ? 'word' : 'words'} to learning set</button></div></div>;
}

export default Wordpanel;
